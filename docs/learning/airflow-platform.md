# Lesson: how this Airflow platform is designed, and why

This page explains the seven main design choices of airflow-platform in plain words. For each one you get:

- **What it is:** the choice in one or two sentences.
- **The problem it solves:** what goes wrong without it.
- **Data-engineering analogy:** the same idea in a place you already know.
- **What would change in a company:** how a bigger team would grow it.

At the end there are 8 interview-style questions with short answers.

The formal records are the [spec](../spec.md) and the ADRs ([0001](../adr/0001-thin-orchestrator.md),
[0002](../adr/0002-self-hosted-vm-compose.md), [0003](../adr/0003-project-views-as-external-views.md)). The
diagrams are in [architecture.md](../architecture.md). The words are in [CONTEXT.md](../../CONTEXT.md).

---

## 1. Thin orchestrator

**What it is.** The Airflow image contains Airflow and its providers, and nothing else. It is installed with
Airflow's official constraints file, which pins every library to a version that is known to work. All real work
(dbt, profiling, ML, a Python script) runs in a separate container image, called a **workload**. A DAG starts the
workload with `DockerOperator`. Airflow only decides *when* and *in what order*. It never runs *what*.

**The problem it solves.** If every project installs its libraries into Airflow, the image becomes a shared
`requirements.txt` for the whole company. Project A needs `pandas<2`, project B needs `pandas>=2`, and Airflow
itself needs a third version of something. You cannot upgrade anything without breaking something else. One bad
import in one DAG file can also slow down or break the scheduler for everyone.

**Data-engineering analogy.** A warehouse scheduler (or dbt Cloud, or a cron server) should not contain the
business logic. It calls stored procedures, dbt models or jobs. In the same way, Airflow here is the conductor of
an orchestra: it points at the musicians, but it doesn't play any instrument itself.

**What would change in a company.** The idea stays. The executor changes: on Kubernetes you use
`KubernetesPodOperator` instead of `DockerOperator`, and each task becomes a pod. Workload images are built by each
team's CI and pushed to a shared registry (ECR, Artifact Registry). A platform team owns the Airflow image. Product
teams own their workload images and never ask the platform team to install a library.

---

## 2. Socket proxy

**What it is.** To start a container, Airflow needs to talk to Docker. The usual shortcut is to mount the Docker
socket (`/var/run/docker.sock`) into the Airflow containers. Here, only one small service, `docker-proxy`, gets the
socket. Airflow talks to the proxy over `tcp://docker-proxy:2375`. The proxy lets through only the API parts
`DockerOperator` needs: containers, images and POST requests.

**The problem it solves.** Full access to the Docker socket is the same as root on the host. Anyone who can write a
DAG, or anyone who breaks into the Airflow UI, could start a privileged container and take over the machine. The
proxy makes the hole smaller: no access to volumes, networks, swarm, secrets or system calls. It is not a full
sandbox, but it removes the easy paths.

**Data-engineering analogy.** It is like a database role with only `SELECT` and `INSERT` on two schemas, instead of
giving the ETL job the superuser password. Least privilege: give each part only what it needs to do its job.

**What would change in a company.** On Kubernetes the proxy goes away. Instead, Airflow gets a service account
with RBAC that can only create pods in one namespace, plus pod security rules (no privileged pods, no host
mounts). On a VM, a company might also run rootless Docker, or a separate "runner" machine for workloads.

---

## 3. DAG bundles

**What it is.** Airflow 3 can load DAGs from several **bundles**. A bundle is a named source of DAG files: a local
folder (`LocalDagBundle`) or a Git repository (`GitDagBundle`). Here every project has its own bundle. The list is
generated from `projects/projects.yaml`, and each project folder is mounted read-only. The platform repo never
copies a project's DAG files.

**The problem it solves.** In the old model there is one `dags/` folder, and every project copies its files into
it. Ownership is unclear, a file from one team can overwrite another team's file, and DAG code is far from the code
it runs. With bundles, each project keeps its DAGs in its own repo, next to its own code and tests. Adding a
project is one YAML entry. The UI shows which bundle each DAG came from.

**Data-engineering analogy.** It is like a data catalog with one source per team, or dbt packages: each package
lives in its own repo with its own version, and the main project only lists them in `packages.yml`. Here
`projects.yaml` plays the role of `packages.yml`.

**What would change in a company.** You would switch to `GitDagBundle` with a pinned branch or tag per project, so
a release of a project is a Git tag, not a file copy. The YAML field and the render code already exist and are
unit-tested, but they are not switched on. A company would also add CI in each project repo that parses its DAGs
against the platform's Airflow version before merge.

---

## 4. External views (project views)

**What it is.** A project can have its own UI (governor has a Streamlit app). The platform shows that UI *inside*
Airflow in three ways: a nav entry, a tab on the DAG page (both use Airflow's `external_views`, an iframe), and a
task link (an operator extra link) that opens the project's page for that exact run. One generic plugin builds all
three from `projects.yaml`. The project serves its own UI; Airflow only links to it.

**The problem it solves.** Users want to go from "the run succeeded" to "show me the result" in one click. The
other ways to do this would put project code inside Airflow: a React plugin (still experimental in Airflow 3.1+,
and its backend would run inside Airflow's process) or a custom plugin per project. Both break the thin
orchestrator rule.

**Data-engineering analogy.** It is like a BI dashboard that links to a report in another tool with the right
filter in the URL, instead of copying that tool into the dashboard. Or a dbt docs link from a data catalog: the
catalog points, the other tool shows.

**What would change in a company.** The project UIs would sit behind the same single sign-on as Airflow, so the
iframe does not ask for a second login. Each project would get a proper hostname instead of `localhost:8501`. If
Airflow's React plugin API becomes stable, a project could get a native-looking page behind the same YAML entry.

---

## 5. One VM running the same compose stack

**What it is.** In the cloud, the platform is one virtual machine. cloud-init installs Docker, clones this repo and
starts the **same** Docker Compose file that runs on the laptop. The metadata database is a Postgres container on
the VM's disk. There is no Kubernetes, no managed Airflow (MWAA, Composer) and no Celery.

**The problem it solves.** Managed Airflow costs a few hundred euros a month even when idle, and it lets you install
only what the service allows. Kubernetes is powerful but needs a cluster, Helm, ingress and a lot of knowledge,
which is too much for one person and a demo. Most of all, "it works on my laptop but not in the cloud" goes away,
because both places run the same file.

**Data-engineering analogy.** It is like using the same dbt project and the same profile structure in dev and in
prod, only with a different target. You test locally, and the cloud is "the same thing, somewhere else".

**What would change in a company.** For more load or high availability: Kubernetes with the official Airflow Helm
chart, a managed database (RDS, Cloud SQL), several schedulers, and remote task logs in object storage. The
Terraform here already has a variable path for a managed DB (documented) and a registry flag. The DAGs and
workloads would not change, because they are already containers.

---

## 6. Time-to-live (TTL)

**What it is.** When `ttl_minutes > 0`, the VM deletes itself after that time. On AWS, cloud-init runs
`shutdown -h +N`, and the instance is set to *terminate* (not just stop) on shutdown. On GCP the VM has
`max_run_duration` with the action `DELETE`. The smoke test uses 90 minutes. On top of that, `smoke.ps1` destroys
everything in a `finally` block and then checks that no smoke VM is left.

**The problem it solves.** The classic cloud mistake: you start a test machine, your laptop crashes or you forget,
and a month later there is a bill. With a TTL, the worst case is 90 minutes of a small VM, which is cents. The
budget alert is the last safety net.

**Data-engineering analogy.** It is like a retention policy or a `TTL` on a temporary table: scratch data deletes
itself, so nobody needs to remember to clean up. Or a `LIMIT` on a query in development, so a mistake stays small.

**What would change in a company.** Long-running environments would not have a TTL, but every sandbox and
pull-request environment would. A company would add tagging rules (owner, cost centre, expiry date), a nightly job
that deletes expired resources, and budget alerts per team.

---

## 7. Terraform tests with mock providers

**What it is.** The Terraform modules are tested without a cloud account. `terraform test` runs `plan` with
`mock_provider`, which pretends to be AWS or GCP and returns fake values. The tests check the rules that matter: no
ingress from `0.0.0.0/0`, at least 4 GB of memory, the TTL is set when asked, no registry when it is switched off,
secret slots have no values, IMDSv2 on AWS, the IAP-only firewall on GCP. CI also runs `fmt`, `validate` and
`tflint`, and an optional `checkov` security scan that only reports.

**The problem it solves.** Infrastructure code is often "tested" only by running it against a real account. That
costs money, needs credentials in CI and is slow. Mock-provider tests are free, fast and safe, so they can run on
every push. They catch logic mistakes (a wrong condition, a missing rule). They do not catch cloud-side problems
(a wrong AMI, a missing API, a quota), which is why a short, real smoke test exists too.

**Data-engineering analogy.** It is like dbt unit tests with mock input rows, or testing a SQL transformation on a
small fixture instead of on the production warehouse. You check the logic cheaply, and run a real end-to-end check
less often.

**What would change in a company.** CI would also run `terraform plan` against a real non-production account, with
short-lived credentials through OIDC (no stored keys). A policy tool (OPA, Sentinel or checkov with `soft_fail`
off) would block merges that break security rules. A nightly job would apply and destroy a test environment.

---

## Interview questions

**1. Why not just `pip install` the project's libraries into the Airflow image?**
Because all projects then share one Python environment with Airflow. Their versions conflict, upgrades break
things, and one bad import can hurt the scheduler. With a thin orchestrator, each workload has its own image and
its own dependencies, and Airflow only starts containers.

**2. What does `DockerOperator` do here, and what would replace it on Kubernetes?**
It asks Docker to run a workload image with a command, streams the container's log into the task log and fails
the task if the container fails. On Kubernetes, `KubernetesPodOperator` does the same with a pod.

**3. Why put a proxy in front of the Docker socket?**
The raw socket is equal to root on the host. The proxy only allows the API calls that `DockerOperator` needs
(containers, images, POST), so a compromised Airflow cannot easily take over the machine. It is least privilege.

**4. What is a DAG bundle, and why does every project get its own?**
A bundle is a named source of DAG files, a folder or a Git repo. One bundle per project keeps DAGs in the
project's repo, makes ownership clear and lets a project join with one YAML entry. Later, a Git bundle can pin a
project to a branch or tag.

**5. How does a project's UI appear in Airflow without running project code in Airflow?**
Through `external_views` (an iframe in the nav and on the DAG page) and an operator extra link on the task. Both
only hold URLs. The project serves its own UI, so Airflow stays thin.

**6. Why one VM with Docker Compose instead of MWAA, Composer or Kubernetes?**
Cost and sameness. It costs cents for a test, it runs the exact same stack as the laptop, and it is simple enough
for one person. The trade-off is no high availability and limited scale. Kubernetes with Helm is the documented
next step.

**7. How do you make sure a test VM doesn't run up a bill?**
Three layers: a TTL that deletes the VM after 90 minutes even if everything else fails, a `finally` block in
`smoke.ps1` that destroys the stack and checks for leftovers, and a €5 budget alert per account.

**8. How can you call Terraform "tested" if it never touched a cloud?**
`terraform test` with mock providers checks the module's logic and its security rules on every push, for free.
That covers mistakes in our code. Cloud-side problems need a real run, so a short smoke test exists for that,
and the README says plainly whether it has been run.
