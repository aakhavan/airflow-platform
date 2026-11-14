# airflow-platform

A reusable, self-hosted Apache Airflow 3 platform. One repo holds the Airflow image, a small local stack, a way for
other repos (**projects**) to plug in their DAGs and their UI, and Terraform that runs the same stack on one VM in
AWS or GCP.

## What and why

**The problem.** In many Airflow setups, every project installs its Python libraries into the Airflow image: dbt,
pandas, LangChain, a Streamlit app, and so on. Soon two projects need two versions of the same library. Upgrading
Airflow breaks a project, and upgrading a project breaks Airflow. The image grows, and nobody dares to touch it.

**The answer: a thin orchestrator** ([ADR 0001](docs/adr/0001-thin-orchestrator.md)).

- The Airflow image holds **Airflow and its providers only**, installed with the official constraints file.
- Every piece of real work is a **workload**: its own container image, started by `DockerOperator`.
- A project joins with **one entry** in [`projects/projects.yaml`](projects/projects.yaml). Its DAGs load as a
  DAG bundle, and its UI shows up inside Airflow as a link and a tab.
- The **same Docker Compose stack** runs on your laptop and on one cloud VM
  ([ADR 0002](docs/adr/0002-self-hosted-vm-compose.md)).

Words used here (orchestrator, workload, project, project view, target, secret slot) are defined in
[CONTEXT.md](CONTEXT.md). The diagrams are in [docs/architecture.md](docs/architecture.md).

## Quick start

Works on Windows and on Linux. You need:

- **Docker Desktop** (Windows) or Docker Engine with the compose plugin (Linux). Give Docker at least 4 GB of RAM;
  the stack uses under 3 GB when idle.
- **[uv](https://docs.astral.sh/uv/)**. It installs Python 3.12 and the small host tooling by itself.
- **PowerShell 7.2 or newer** (`pwsh`). On Linux, install the `powershell` package.

Then, from the repo root:

```powershell
pwsh scripts/up.ps1
```

`up.ps1` copies `stack/.env.example` to `stack/.env` the first time, renders the project files, builds the images
and starts the stack. It waits until every service is healthy. The first run pulls about 1.5 GB.

The default registry, `projects/projects.yaml`, also lists governor, which expects a governor checkout next to
this repo. Without it, `up.ps1` stops with an error that names the missing path. Then start with the
examples project only:

```powershell
pwsh scripts/up.ps1 -Projects projects/ci.yaml
```

1. Open <http://localhost:8080>. Log in with the local defaults from `stack/.env.example` (`airflow` / `airflow`).
2. Find the DAG `hello_workload` (tag `platform`) and press **Trigger**.
3. Open the run. The task `hello` starts the `workloads/hello` container. Its greeting and one JSON line appear
   in the task log, and the run ends in `success`.

Other useful commands:

```powershell
pwsh scripts/status.ps1                       # one JSON line: services, health, memory
uv run python -m airflow_platform.stack status --dags   # active DAGs and their bundles
pwsh scripts/down.ps1                         # stop; keeps the database
pwsh scripts/down.ps1 -Volumes                # stop and delete the database
```

## Add a project

A project is a repo with its own DAGs, workload images and (optionally) its own UI. To plug it in, add one entry
to `projects/projects.yaml`:

```yaml
projects:
  - name: my-project                      # [a-z0-9-], unique
    dags: {local: ../../my-project/airflow/dags}   # relative to projects.yaml, forward slashes
    view: {label: My project, url: "http://localhost:8501"}            # optional
    task_link:                                                         # optional
      label: "Open report"
      url_template: "http://localhost:8501/report?run_id={run_id_safe}"
      dag_prefix: "my_project_"
```

Then run `pwsh scripts/up.ps1` again. No platform code changes. You get:

- **A DAG bundle.** The folder is mounted read-only at `/opt/airflow/projects/my-project` and loaded as its own
  `LocalDagBundle`. The DAGs show the bundle name in the UI.
- **A nav entry** (under Browse) that opens the project's UI inside Airflow, if you set `view`.
- **A DAG tab** with the same UI on the DAG page, if you set `view`. Airflow 3.3 cannot limit a tab to some DAGs,
  so the tab shows on every DAG.
- **A task link** on every task of a DAG whose id starts with `dag_prefix`, if you set `task_link`. It opens the
  project's page for that exact run. Placeholders: `{run_id}`, `{run_id_safe}` (`:` replaced by `_`), `{dag_id}`,
  `{task_id}`.

The rules: a project's DAG imports only Airflow, providers and the standard library. Its real code runs in its own
workload image. Its UI is served by the project, never by Airflow
([ADR 0003](docs/adr/0003-project-views-as-external-views.md)).

The first real project is **governor**: a manual DAG profiles a Postgres schema in governor's own container, and
the task link opens the report in governor's Streamlit app. See [docs/projects/governor.md](docs/projects/governor.md).

## Targets

| Target | What exists | How it is tested |
|---|---|---|
| `local` | The compose stack, built and running | Offline `pytest`, plus CI that starts the stack, checks for zero DAG import errors and runs `hello_workload` to `success` |
| `aws` | Terraform module `airflow-vm-aws` and `envs/aws` | `fmt`, `validate`, `tflint` and `terraform test` with **mock providers** (no account, no cost) |
| `gcp` | Terraform module `airflow-vm-gcp` and `envs/gcp` | The same, with mock providers |

**Smoke-tested in a real cloud: not yet.** The scripts `plan.ps1`, `smoke.ps1`, `tunnel.ps1` and
`remote-state.ps1` have only run with `-WhatIf`. A real smoke run writes `logs/smoke-<target>-<ts>.json`; none
exists yet.

On a cloud target, the VM has **no public ports**. You reach the UI through an AWS SSM port-forward or a GCP IAP
tunnel: `pwsh scripts/tunnel.ps1 -Target gcp`, then <http://localhost:8080>. Step by step:
[docs/runbook.md](docs/runbook.md).

## Cost and safety

- **Local costs nothing.** Only your own machine runs.
- **A forgotten VM deletes itself.** With `ttl_minutes > 0` the VM has a time-to-live (TTL). On AWS it shuts down
  after the TTL and is then terminated. On GCP `max_run_duration` deletes it. The smoke test uses 90 minutes.
- **`smoke.ps1` cleans up.** It runs apply → healthy → `hello_workload` → destroy. The destroy is in a `finally`
  block, so it runs even when a step fails. After that, it searches for any left-over smoke VM and fails loudly
  if one is still there. It prints a cost estimate (about $0.10 per run) and asks before it applies.
  Run it with `-WhatIf` first: that shows every command and runs none.
- **Budget alert.** Before the first apply, create a €5 monthly budget alert in each cloud account, by hand, once.
- **Agents and CI never touch a cloud account.** They run only `fmt`, `validate`, `init -backend=false` and
  `terraform test` with mock providers.

## Configuration and secrets

- **Local:** each repo has one `.env` file, made from its `.env.example` and ignored by git. Nothing is global.
  For this repo that is `stack/.env`. The example holds only the documented local defaults.
- **Cloud:** Terraform creates **empty secret slots** (AWS Secrets Manager, GCP Secret Manager). You fill them by
  hand. At boot the VM reads them with its own identity and writes `stack/.env`. No secret is in Terraform, in the
  state, in an image or in a committed file.
- **CI:** no cloud secrets at all. Later, a cloud login for CI would use OIDC (short-lived tokens, no stored keys).
- **Optional upgrade:** a password-manager CLI (for example 1Password or Bitwarden) that injects the values when
  you start a command, so no `.env` file sits on disk.

## Limits and future targets

- **One VM.** The cloud target is a single VM with the compose stack and `LocalExecutor`. It has no high
  availability, and it scales up (a bigger VM), not out.
- **Kubernetes + Helm** is the next target when one VM is not enough: the official Airflow Helm chart and
  `KubernetesPodOperator`. Workloads are already containers, so the DAG pattern stays the same.
- **Managed database.** The metadata database is a container on the VM's disk. A managed database (RDS, Cloud SQL)
  would sit behind a Terraform variable. It is documented, not built.
- **Git bundles.** In the cloud, project DAGs should come from Git (`GitDagBundle`) instead of a local folder. The
  YAML field and the render code exist and are unit-tested, but they are not enabled.
- **Container registry** (ECR / Artifact Registry) exists behind `enable_registry = false`. By default the VM
  builds images from git.
- **Governor `build run` with a human in the loop.** Today the governor DAG only profiles (read-only). A run that
  needs a person's approval between steps comes later.

## Repo map

- [docs/spec.md](docs/spec.md): the build contract (decisions, layout, every step).
- ADRs: [0001 thin orchestrator](docs/adr/0001-thin-orchestrator.md),
  [0002 one VM with compose](docs/adr/0002-self-hosted-vm-compose.md),
  [0003 project views](docs/adr/0003-project-views-as-external-views.md).
- [CONTEXT.md](CONTEXT.md): the glossary.
- [docs/architecture.md](docs/architecture.md): diagrams of the local and the cloud target.
- [docs/projects/governor.md](docs/projects/governor.md): runbook for the governor project.
- [docs/runbook.md](docs/runbook.md): cloud plan, smoke test and cleanup.
- [docs/learning/airflow-platform.md](docs/learning/airflow-platform.md): the design explained as a lesson.
- Code: `stack/` (compose), `image/` (Airflow image), `src/airflow_platform/` (host tooling), `plugins/` (project
  views), `workloads/`, `terraform/`, `scripts/`, `tests/`.

### CI

`.github/workflows/ci.yml` runs on every push and pull request, with no secrets:

- `python`: `uv sync --frozen` and `pytest -q`.
- `stack`: starts the stack with `projects/ci.yaml`, checks for zero DAG import errors, runs `hello_workload`,
  and always tears down with volumes. On failure it uploads the compose logs.
- `terraform`: `fmt`, `validate`, `tflint` and `terraform test` with mock providers.
- `checkov`: a security scan of the Terraform. It only reports (`soft_fail`), it never fails the build.

To run the stack job on your machine: `pwsh scripts/ci-local.ps1`. It uses its own compose project on port 8081,
so your dev stack on 8080 keeps running.

## License

[MIT](LICENSE).
