# airflow-platform: build spec

*Written 13 Nov 2026 from a grilling session with Amir (decisions Q1–Q26). Built by the code factory: Turing Claude Opus implements; Cursor Grok or Fable reviews. The step prompts point at sections of this file; read only the section your prompt names.*

---

## 1. What this is

A **reusable, self-hosted Airflow platform**: one repo holding the Airflow image, a lean local stack, a mechanism for other repos (**projects**) to plug in their DAGs and their UI, and Terraform that can run the same stack on one VM in AWS or GCP.

- **Capstone use (this weekend):** the local stack runs, and governor plugs in as the first project. A manual-only DAG runs `governor.build profile` as a container, and governor's Streamlit UI shows up inside Airflow. It's optional for the submission: Amir decides on Saturday whether it goes in.
- **Longer term:** a template Amir can take into a company. Workloads stay containers, Terraform stays boring, and a project joins with one YAML entry.
- **Out of scope:** Kubernetes/Helm (named as a future target in the README), managed MWAA/Composer, Celery, and any real cloud apply by an agent.

## 2. Decisions (locked)

| # | Decision | Why |
|---|---|---|
| D1 | Separate project-agnostic repo `airflow-platform` | Reusable; keeps project dependencies out of Airflow |
| D2 | **Thin orchestrator** (ADR 0001): the Airflow image holds Airflow and providers only, installed with the official constraints file. Every workload is its own container image, launched by `DockerOperator` | Removes the dependency conflicts; the same workload image runs everywhere |
| D3 | Airflow **3.3.x**, latest patch, pinned exactly; Python 3.12 image variant | Current line; check the patch at S1 |
| D4 | `LocalExecutor`, Postgres metadata DB in a container. No Redis, no Celery | Tasks are only container launches |
| D5 | Self-hosted **one VM per cloud running the same compose stack** (ADR 0002). Kubernetes is a README "future target" | "Flawless" = local and cloud identical; no Kubernetes cost |
| D6 | Metadata DB on the VM (container + persistent disk); a managed DB would sit behind a Terraform variable that is **documented, not built** | Cheap now, one switch later |
| D7 | Container registry (ECR / Artifact Registry) behind `enable_registry = false`. By default the VM builds images from git with `docker build` | No spend; the company path exists as a flag |
| D8 | Secrets: `.env` locally (never committed, agents never read it). In the cloud, Airflow's secrets backend (AWS Secrets Manager / GCP Secret Manager) is read through the VM identity. Terraform creates **empty** secret slots | No secret values in code, state or agents |
| D9 | No public ports. The UI is reached through an AWS SSM port-forward or a GCP IAP tunnel (`tunnel.ps1`) | The UI can launch containers: it is a control plane |
| D10 | Terraform state is **local** by default; `remote-state.ps1` creates an S3/GCS bucket and migrates when Amir wants | No company repo yet, no cost yet |
| D11 | Project DAGs live in the project's repo and load through Airflow 3 **DAG bundles** (local folder now, Git bundle later), generated from `projects/projects.yaml` | The platform never learns project code |
| D12 | **Project views** (ADR 0003): a project's UI appears in Airflow as a nav entry + DAG tab (`external_views`, iframe) and a task link (operator extra link). No React plugin, no project code in Airflow's process | React apps are experimental in Airflow 3.1+; keeps D2 |
| D13 | Governor DAG: **manual-only** (`schedule=None`) `governor.build profile` of the raw Olist schema. Read-only, no LLM. `build run` with human-in-the-loop operators is post-submission | Safe, cheap, demoable; certify is a human command and stays one |
| D14 | Terraform tested without credentials: `fmt`, `validate`, `tflint`, `terraform test` with `mock_provider`. `plan.ps1` is Amir's (free, read-only, needs his credentials) | "Tested Terraform" without spending |
| D15 | Cloud smoke test is **Amir's**, optional, and costs cents: `smoke.ps1` runs apply → healthy → hello DAG → destroy in `finally`. The VM has a **TTL** (AWS: `shutdown -h +90` + `instance_initiated_shutdown_behavior = "terminate"`; GCP: `max_run_duration` 90 min + `instance_termination_action = "DELETE"`). Amir creates a €5 budget alert per account once, by hand | A forgotten VM costs cents, not a month |
| D16 | Scripts are PowerShell (`scripts/*.ps1`, run with `pwsh`), so they run on Amir's Windows machine and on GitHub's Ubuntu runners. The VM side is bash (cloud-init) | Amir is on Windows; CI is Linux |

## 3. Layout

```
airflow-platform/
  AGENTS.md  CONTEXT.md  README.md  NOTES.md  STATUS.md  plan.yaml  plan/  docs/{spec.md, adr/}
  pyproject.toml            # uv project for host-side tooling and tests only: pyyaml, pytest. Never apache-airflow.
  image/
    Dockerfile              # FROM apache/airflow:<3.3.x>-python3.12; pip install providers with the constraints URL
    requirements.txt        # providers only (docker, standard, git, amazon, google), unpinned: the constraints file pins them
  stack/
    compose.yaml            # postgres, airflow-init, api-server, scheduler, dag-processor, triggerer, docker-proxy
    compose.projects.yaml   # GENERATED from projects.yaml: bind mounts of project DAG folders
    .env.example            # names only; the real .env is git-ignored
    versions.yaml           # every image tag, provider and tool version in use
  src/airflow_platform/
    projects.py             # load + validate projects.yaml; render bundles JSON and the compose override (pure)
    stack.py                # python -m airflow_platform.stack up|down|status|render|trigger|wait
  plugins/project_views/__init__.py   # AirflowPlugin: external_views + operator extra links from projects.yaml (stdlib + yaml only)
  projects/projects.yaml    # the registry of projects
  dags/examples/hello_workload.py     # the platform's own example bundle
  workloads/hello/{Dockerfile, main.py}
  scripts/  up.ps1 down.ps1 status.ps1 plan.ps1 smoke.ps1 tunnel.ps1 remote-state.ps1
  terraform/
    modules/airflow-vm-aws/  modules/airflow-vm-gcp/   # each: main.tf variables.tf outputs.tf versions.tf tests/*.tftest.hcl
    templates/cloud-init.yaml.tftpl                    # shared: install docker, clone repo, render .env from secrets, compose up, TTL
    envs/aws/  envs/gcp/                               # thin root modules + terraform.tfvars.example
  .github/workflows/ci.yml
  tests/                    # offline pytest: no Docker, no network, no Airflow import
```

## 4. Local stack (S1)

- Start from the **official `docker-compose.yaml` for the pinned 3.3.x release** (record the URL and date in `stack/versions.yaml`) and trim it:
  - drop redis, airflow-worker and flower;
  - set `AIRFLOW__CORE__EXECUTOR: LocalExecutor`;
  - keep postgres, airflow-init, api-server, scheduler, dag-processor and triggerer;
  - set `AIRFLOW__CORE__LOAD_EXAMPLES: "false"`.
- The compose project name is `airflow_platform`. The UI is on `localhost:8080` (configurable through `AIRFLOW_PORT`).
- Every service has a healthcheck. Resource target: the **whole stack uses under 3 GB RAM** at idle (`docker stats --no-stream`).
- The image is built from `image/Dockerfile`, tagged `airflow-platform:local`. Providers come from the constraints file `https://raw.githubusercontent.com/apache/airflow/constraints-<version>/constraints-3.12.txt`. Nothing else is installed.
- Local credentials are the documented defaults of the official compose file for the auth manager it uses (verify: Simple auth manager in 3.x). They are written only to `.env.example` as defaults.
- `python -m airflow_platform.stack status` prints one JSON line last:
  - `{"up": bool, "services": {name: health}, "airflow_version": str, "url": str, "mem_mb": int}`.
- `scripts/up.ps1` renders the generated files, builds and runs `docker compose up -d --wait`. `down.ps1` keeps volumes unless `-Volumes`. `status.ps1` wraps `status`.

## 5. Workloads (S2)

- A **workload** is a container image plus a command. DAGs launch it with `DockerOperator` (provider `apache-airflow-providers-docker`).
- Docker access goes through a **socket proxy** service (`tecnativa/docker-socket-proxy`, pinned) with only the API sections `DockerOperator` needs (CONTAINERS, IMAGES, POST, and whatever else the provider proves to need; record which). Airflow uses `docker_url="tcp://docker-proxy:2375"`. The raw socket is never mounted into an Airflow container.
- On Docker Desktop, set `mount_tmp_dir=False` (known issue with the temporary bind mount). Log lines from the container must appear in the task log.
- `workloads/hello` is a tiny image (python slim + `main.py`). It prints a greeting and one JSON line, and exits 0. `dags/examples/hello_workload.py` (`schedule=None`, tag `platform`) runs it.
- **The isolation rule is checked:** `pip list` inside `airflow-platform:local` must contain none of `dbt-core`, `langchain`, `langgraph`, `pandas`, `governor`, `streamlit` (a denylist in the acceptance script).
- `python -m airflow_platform.stack trigger <dag_id> [--conf JSON]` and `wait <dag_id> <run_id> --timeout S` use the Airflow REST API v2 (token from `POST /auth/token` with the local defaults; verify the exact route on the running server's `/docs`). Each prints one JSON line with `state`.

## 6. Projects and DAG bundles (S3)

`projects/projects.yaml`:

```yaml
projects:
  - name: examples                 # [a-z0-9-], unique
    dags: {local: ../dags/examples}      # path relative to this file; mounted read-only
  - name: governor                 # added in S5
    dags:
      local: ../../governor-airflow/airflow/dags   # the worktree until the branch is merged, then ../../governor/airflow/dags
      git: {repo_url: "https://github.com/aakhavan/governor", subdir: airflow/dags, tracking_ref: main}   # cloud; documented, not enabled
    view: {label: Governor, url: "http://localhost:8501"}
    task_link: {label: "Open report", url_template: "http://localhost:8501/Profiles?run_id={run_id_safe}", dag_prefix: "governor_"}
```

- `projects.py` validates the file: unique names, existing local paths, `url_template` containing only `{run_id}`, `{run_id_safe}` (the run id with `:` replaced by `_`, the form projects use for file names), `{dag_id}` and `{task_id}`. Errors name the project and the field.
- It renders two things from it:
  1. `AIRFLOW__DAG_PROCESSOR__DAG_BUNDLE_CONFIG_LIST`: one `LocalDagBundle` per project, with path `/opt/airflow/projects/<name>`, written into `stack/.env.generated` (git-ignored). Verify the class path and the kwargs against the 3.3 docs.
  2. `stack/compose.projects.yaml`: a read-only bind mount per project into the dag-processor, scheduler and triggerer (and anywhere else the 3.3 docs say bundles are read).
- Git bundles are rendered only with `--target cloud`, and need the git provider. They are covered by a unit test, not run live.
- Adding a project means one YAML entry + `up.ps1`. Nothing in the platform's code changes.

## 7. Project views plugin (S4)

`plugins/project_views/__init__.py` defines one `AirflowPlugin` (Airflow 3.1+ API) and reads `projects.yaml` (mounted at `/opt/airflow/projects/projects.yaml`). It uses no third-party imports beyond `yaml`, which Airflow already ships.

For each project with a `view`, it registers:

- `external_views`: a **nav** entry (category `browse`), plus a **dag** tab named after the project. Verify whether a tab can be limited to DAGs with a given id prefix or tag. If it can't, keep the tab on all DAGs and record the finding.

For each project with a `task_link`, it registers:

- a `BaseOperatorLink` subclass whose `get_link` returns the formatted URL when `ti_key.dag_id` starts with `dag_prefix`, and an empty string otherwise. It is registered through `global_operator_extra_links`. Verify the 3.3 signature: `get_link(self, operator, *, ti_key)`.

**Rules:**

- No `fastapi_apps`, no `react_apps`, no Flask.
- A broken `projects.yaml` must not break Airflow. The plugin logs one warning and registers nothing.
- Acceptance reads `GET /api/v2/plugins` (verify the route) and checks the names and hrefs. The pure functions (`views_for(projects)`, `link_for(project, ti_key)`) are unit-tested offline.

## 8. Governor integration (A1 in governor, S5 here)

The factory commits only inside the repo its plan lives in. So:

**A1** runs as its own one-step plan **in a governor worktree**:
- Folder: `C:\Users\amir0\portfolio\governor-airflow`.
- Branch: `airflow-integration`, from `main`.
- Files: `plan-airflow.yaml`, `plan/prompts/A1.md`, `plan/accept/accept_a1.py`.

Amir's uncommitted changes in `governor` (README, LICENSE, ethics) are untouched, because the worktree is a separate folder. A1 adds:

1. **`airflow/dags/governor_profile_raw.py`**: `dag_id="governor_profile_raw"`, `schedule=None`, tags `["governor"]`. It defines one `DockerOperator` task `profile`:
   - **image:** `governor:local`, the existing governor image; no new Dockerfile;
   - **command:** `python -m governor.build profile --schema raw --policy knowledge/shop/policy.yaml --out /data/profiles/{{ run_id | replace(':', '_') }}.json`;
   - **mount:** the governor data volume at `/data`. The name comes from an Airflow Variable `governor_data_volume`, default `governor_governor-data`; verify the real name with `docker volume ls`;
   - **environment:** `GOVERNOR_PG_HOST` (default `host.docker.internal`), `GOVERNOR_PG_PORT`, `GOVERNOR_PG_DB`, `GOVERNOR_BUILD_USER` and `GOVERNOR_BUILD_PASSWORD`, all from **Airflow Variables or a connection**, rendered at run time. Never a literal password in the DAG file. The local defaults may live in the platform's `.env.example`, which already documents them in governor's `testbed/README.md`;
   - `mount_tmp_dir=False` and `docker_url` from the Variable `docker_url`, default `tcp://docker-proxy:2375`.

   The DAG file imports only Airflow, providers and the standard library. **It must not import `governor`.**
2. **`src/governor/api/profiles.py`**: a router with `GET /profiles` (list run ids) and `GET /profiles/{run_id}`, reading `$GOVERNOR_STATE_DIR/profiles/`. It uses the **same auth dependency as the existing routes**, validates `run_id` against `^[A-Za-z0-9_.+-]+$` (no path traversal), and returns the stored JSON unchanged.
3. **One registration line** in `src/governor/api/app.py` (`include_router`). This is the only existing file A1 may edit.
4. **`apps/streamlit/pages/4_Profiles.py`**: lists profiles and shows one, by the `run_id` query param, through the existing `client.py`. Tables, row counts and relationships go in a table; PII columns are shown as the profile marks them.
5. Tests (offline, governor's style): the router lists and returns a stored profile, refuses a traversal id and needs auth. **All existing governor tests stay green.**

**S5** (this repo) adds the governor entry to `projects.yaml` (§6) and a `docs/projects/governor.md` runbook:
1. Start the governor testbed and the governor compose stack.
2. Run `up.ps1`.
3. Trigger `governor_profile_raw` from the UI.
4. Open the report from the task link.

S5's acceptance runs that end to end.

**Cut line:** A1 + S5 must be merged by **Sat 14 Nov 12:00**. If not, the branch stays unmerged, governor `main` stays frozen, and the capstone ships without it.

## 9. Terraform (S7, S8)

Both modules share one cloud-init template (`templates/cloud-init.yaml.tftpl`). It:

1. installs Docker Engine + the compose plugin from the official repo;
2. clones `airflow-platform` (variable `repo_url`, `repo_ref`);
3. renders `stack/.env` **from the secrets backend at boot** (`aws secretsmanager get-secret-value` / `gcloud secrets versions access`), never from Terraform variables;
4. runs `pwsh`-free bash equivalents of `up.ps1` (`python3 -m airflow_platform.stack render` + `docker compose up -d --wait`);
5. if `ttl_minutes > 0`, runs `shutdown -h +<ttl>`.

| | AWS (`airflow-vm-aws`) | GCP (`airflow-vm-gcp`) |
|---|---|---|
| Compute | `aws_instance`, default `t3.medium`, Ubuntu 24.04 LTS (AMI via SSM public parameter), gp3 30 GB, IMDSv2 required | `google_compute_instance`, default `e2-medium`, Ubuntu 24.04 LTS, pd-balanced 30 GB, Shielded VM |
| Network | default VPC by variable, security group with **no ingress**, egress all | firewall: **no ingress** except IAP range `35.235.240.0/20` on 22/8080 |
| Access | instance profile with `AmazonSSMManagedInstanceCore`; `tunnel.ps1` uses `aws ssm start-session` port-forward | service account; `tunnel.ps1` uses `gcloud compute start-iap-tunnel` |
| Secrets | `aws_secretsmanager_secret` slots (no versions) for `airflow-platform/<name>`; role may read only those | `google_secret_manager_secret` slots (no versions); SA has `secretAccessor` on those only |
| Airflow backend | `SecretsManagerBackend` env in `.env` | `CloudSecretManagerBackend` env in `.env` |
| Registry | `aws_ecr_repository` with `count = var.enable_registry ? 1 : 0` | `google_artifact_registry_repository` likewise |
| TTL | `instance_initiated_shutdown_behavior = "terminate"` when `ttl_minutes > 0` | `scheduling { max_run_duration { seconds = ttl*60 }, instance_termination_action = "DELETE" }` when `ttl_minutes > 0` (verify the provider version that supports it) |
| Outputs | `instance_id`, `tunnel_command`, `secret_names` | `instance_name`, `zone`, `tunnel_command`, `secret_names` |

**Rules:**

- Pin `required_version` (a Terraform version that supports `mock_provider`, 1.7+) and the provider majors. Record them in `stack/versions.yaml`.
- No `terraform.tfvars` committed, only `.example` files.
- No backend block in `envs/*`; `remote-state.ps1` writes `backend.tf` when it is used.
- `terraform test` files in `modules/*/tests/` use `mock_provider` and `command = plan`. They assert:
  - no ingress from `0.0.0.0/0`;
  - instance memory ≥ 4 GB (by type allowlist);
  - the TTL is set when `ttl_minutes > 0`;
  - the registry is absent when `enable_registry = false`;
  - secret slots have no versions;
  - IMDSv2 is required (AWS);
  - the IAP-only firewall is in place (GCP).

## 10. Scripts (S9)

All scripts take `-Target aws|gcp` where relevant, print what they will do, support `-WhatIf`, and never print secret values.

- **`plan.ps1`:** `terraform init` + `plan` in `envs/<target>`, using Amir's own credentials (`aws`/`gcloud` CLI login). Writes the plan summary to `logs/`.
- **`smoke.ps1`:** checks for an existing state (refuses unless `-Force`), then runs these steps:
  1. `apply` with `ttl_minutes=90`;
  2. waits for SSM/IAP to answer;
  3. opens the tunnel;
  4. waits for health;
  5. triggers `hello_workload`;
  6. waits for success.

  Whatever happens, a `finally` block runs `destroy -auto-approve` and then verifies that no instance tagged `airflow-platform-smoke` is left. Results go to `logs/smoke-<target>-<ts>.json`. It prints a cost estimate before applying and asks for `y` unless `-Yes` is given.
- **`tunnel.ps1`:** the port-forward to `localhost:8080`.
- **`remote-state.ps1`:** creates a versioned, private state bucket, writes `backend.tf`, and runs `terraform init -migrate-state`.
- **The agent never runs `plan.ps1` or `smoke.ps1` for real.** Acceptance runs them with `-WhatIf` only, which needs no credentials.

## 11. CI (S6, extended in S9)

`.github/workflows/ci.yml` runs on push and pull requests, on `ubuntu-latest`:

- **`python` job:** uv sync + `pytest -q`.
- **`stack` job:**
  1. `pwsh scripts/up.ps1`;
  2. `airflow dags list-import-errors` in the scheduler container: must be empty;
  3. trigger `hello_workload` and wait for success;
  4. `down.ps1 -Volumes`.
- **`terraform` job** (S9):
  - `terraform fmt -check -recursive`;
  - `init -backend=false` + `validate` per env;
  - `tflint` (pinned action);
  - `terraform test` per module.

No cloud credentials exist in CI. **checkov** (S10) is an optional job with `soft_fail: true`, and the first thing cut.

## 12. Verify first (do not assume)

| Fact | Where to check | Step |
|---|---|---|
| Latest 3.3.x patch, its compose file, and the auth manager plus default login | airflow.apache.org docs and release notes | S1 |
| REST API v2 token route and trigger/get-run routes | the running server's `/docs` | S2 |
| Socket-proxy sections `DockerOperator` needs | try, then record | S2 |
| `LocalDagBundle` class path and kwargs; which services read bundles | 3.3 docs, "DAG bundles" | S3 |
| `external_views` keys (`destination`, `category`, `url_route`); per-DAG filtering of a dag tab; operator-link signature; plugins API route | 3.3 docs, "Plugins" / "Custom view plugin" | S4 |
| Governor data volume name; testbed reachable from a container at `host.docker.internal:55432` on Docker Desktop | `docker volume ls`, a test container | A1 |
| `mock_provider` support and the Terraform version installed; the GCP provider version with `max_run_duration` | `terraform version`, provider changelog | S7/S8 |

When reality differs from this spec, follow reality and write one line under "Open questions" in `NOTES.md`. A finding is a valid result; never fake a check.

## 13. Steps, roles and gates

| Step | Title | Reviewer | Gate |
|---|---|---|---|
| S0 | Scaffold, uv tooling, `projects.py` skeleton, CONTEXT/ADRs present | Grok | — |
| S1 | Image + lean local stack + status | Grok | — |
| S2 | Workload pattern: socket proxy, hello workload, trigger/wait, isolation check | Grok | — |
| S3 | `projects.yaml` → bundles + compose override | Grok | — |
| S4 | Project views plugin | **Fable** | — |
| A1 | *(governor worktree, own plan)* profile DAG, profiles API route, Profiles page | **Fable** | **HUMAN** (Amir, phone) |
| S5 | Governor project entry + end-to-end run | **Fable** | **HUMAN** (cut line Sat 12:00) |
| S6 | CI: python + stack jobs | Grok | — |
| S7 | Terraform AWS module + tests | Grok | — |
| S8 | Terraform GCP module + tests | Grok | — |
| S9 | Scripts (plan/smoke/tunnel/remote-state) + terraform CI job | **Fable** | — |
| S10 | README, architecture diagram, learning page; checkov optional | Grok | **HUMAN** (release) |

**Run order:**

1. Platform S0–S4.
2. A1 in the worktree.
3. Platform S5–S10.

Claude (chat) checks in every 30 minutes. It approves non-HUMAN gates it is confident about, and sends a phone notice for a step that fails twice, for A1, S5 and S10.
