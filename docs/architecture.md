# Architecture

Two pictures: the local target and a cloud target. Both run **the same compose stack**
([ADR 0002](adr/0002-self-hosted-vm-compose.md)). Words are defined in [CONTEXT.md](../CONTEXT.md).

## Local target

Airflow never imports project code. It reads DAG files from read-only bundle mounts and starts workload
containers through a socket proxy that allows only the Docker API calls `DockerOperator` needs
([ADR 0001](adr/0001-thin-orchestrator.md)). A project's UI runs outside Airflow and shows up inside it as a
nav entry, a DAG tab and a task link ([ADR 0003](adr/0003-project-views-as-external-views.md)).

```mermaid
flowchart LR
    user["Browser<br/>localhost:8080"]

    subgraph stack["compose project airflow_platform (image airflow-platform:local)"]
        api["api-server<br/>UI + REST API v2<br/>project_views plugin"]
        sched["scheduler<br/>LocalExecutor"]
        dagp["dag-processor"]
        trig["triggerer"]
        pg[("postgres<br/>metadata DB")]
        proxy["docker-proxy<br/>CONTAINERS, IMAGES, POST only"]
        init["airflow-init<br/>migrate DB, create user"]
    end

    subgraph registry["projects/projects.yaml"]
        reg["one entry per project"]
    end

    subgraph bundles["DAG bundles (read-only mounts)"]
        ex["examples<br/>dags/examples"]
        gov["governor<br/>governor/airflow/dags"]
    end

    subgraph workloads["Workload containers (started per task)"]
        hello["workloads/hello"]
        govimg["governor:local<br/>build profile"]
    end

    subgraph views["Project views (served by the project)"]
        st["governor Streamlit<br/>localhost:8501"]
    end

    docker["Docker Engine<br/>(host socket)"]

    user --> api
    api --> pg
    sched --> pg
    dagp --> pg
    trig --> pg
    init --> pg
    reg -->|"up.ps1 renders bundle list + mounts"| bundles
    reg -->|"plugin reads at import"| api
    bundles --> dagp
    bundles --> sched
    sched -->|"DockerOperator tcp://docker-proxy:2375"| proxy
    proxy --> docker
    docker --> hello
    docker --> govimg
    api -.->|"nav entry, DAG tab, task link"| st
    user -.->|"iframe / link"| st
```

What to notice:

- The raw Docker socket is mounted **only** into `docker-proxy`, never into an Airflow container.
- Workloads are siblings of Airflow on the same Docker Engine, not children inside it.
- `projects.yaml` is the only place a project is named. `up.ps1` turns it into `stack/.env.generated` (the
  `LocalDagBundle` list) and `stack/compose.projects.yaml` (the mounts). Both files are generated and git-ignored.

## Cloud target (AWS or GCP)

Terraform creates one VM with no public ports. cloud-init installs Docker, clones this repo, reads the secret
slots with the VM's own identity, writes `stack/.env` and starts the same compose stack. You reach the UI through
a tunnel. The TTL deletes a forgotten VM. Steps are in the [runbook](runbook.md).

```mermaid
flowchart LR
    subgraph laptop["Your laptop"]
        tf["terraform apply<br/>(you, never an agent)"]
        tun["tunnel.ps1<br/>SSM port-forward / IAP tunnel"]
        browser["Browser<br/>localhost:8080"]
    end

    subgraph cloud["Cloud account (AWS or GCP)"]
        subgraph net["Network: no public ingress"]
            subgraph vm["VM: Ubuntu 24.04, 4 GB RAM, 30 GB disk"]
                ci["cloud-init<br/>install Docker, git clone,<br/>render .env, compose up"]
                stackc["same compose stack<br/>as local"]
                ttl["TTL timer<br/>shutdown -h +N"]
            end
        end
        secrets[("Secret slots<br/>Secrets Manager / Secret Manager<br/>created empty, filled by hand")]
        ident["VM identity<br/>instance profile / service account<br/>read only its own slots"]
        reg[("Registry ECR / Artifact Registry<br/>enable_registry = false")]
        ctrl["Cloud TTL<br/>AWS: terminate on shutdown<br/>GCP: max_run_duration + DELETE"]
    end

    git[("GitHub<br/>airflow-platform repo")]

    tf --> vm
    tf --> secrets
    tf --> ident
    tf -.-> reg
    ci -->|"clone repo_url @ repo_ref"| git
    ci -->|"read at boot"| ident
    ident --> secrets
    ci --> stackc
    ci --> ttl
    ttl --> ctrl
    browser --> tun
    tun -->|"SSM / IAP, port 8080"| stackc
```

What to notice:

- No secret value goes through Terraform, its state, an image or a file in git. Terraform only creates the empty
  slots and the permission to read them.
- The only way in is the cloud's own tunnel (SSM or IAP), which checks your cloud login first.
- The registry is drawn dashed because it is off by default: the VM builds images from git.
