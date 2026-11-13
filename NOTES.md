# NOTES

## Current state
S1 is in place and accept_s1 passed with the stack left running. Project airflow_platform runs Airflow 3.3.2 on the Python 3.12 image with LocalExecutor, Postgres 16, api-server, scheduler, dag-processor, triggerer, and init. Providers docker, standard, git, amazon, and google are installed through the official constraints file. Idle RAM was 1232 MB. The auth manager is FAB, with the documented admin login airflow; spec section 4 had guessed Simple. The local image is 3078 MiB because the official base image is already that size. projects.yaml still registers only examples, and bundle rendering is still the S3 stub. Next is S2, workloads and the Docker socket proxy.

## Open questions
- S1 verify (auth manager): the official 3.3.2 compose file uses the **FAB auth manager** (`airflow.providers.fab.auth_manager.fab_auth_manager.FabAuthManager`), not Simple as spec §4 assumed. Its documented local admin login is `_AIRFLOW_WWW_USER_USERNAME` / `_AIRFLOW_WWW_USER_PASSWORD` = airflow / airflow, created by airflow-init. We kept FAB.
- S1 image size: airflow-platform:local is 3.23 GB, above the 2.5 GB line. All five providers (docker, standard, git, amazon, google) and fab are already preinstalled in `apache/airflow:3.3.2-python3.12` at the constrained versions, and our layer adds about 5 MB. A `CLOUD_PROVIDERS` switch would not shrink anything, so none was added. Only a `-slim` base would, and the spec doesn't allow one.
- S1: Airflow 3.4.0 is already on PyPI. The plan pins 3.3.x, so we use 3.3.2, the latest 3.3 patch.

## S1 result (implementer notes)
- Airflow **3.3.2** (`image/Dockerfile`, one `ARG AIRFLOW_VERSION`). Providers are installed with the official constraints-3.3.2/constraints-3.12.txt. `stack/compose.yaml` is the official 3.3.2 file, trimmed: LocalExecutor, no broker/worker/flower/cli, LOAD_EXAMPLES false, port `${AIRFLOW_PORT:-8080}`, and healthchecks everywhere.
- Auth manager: FAB, admin login airflow/airflow (the documented default, only in `stack/.env.example`).
- `airflow-init` is one-shot: `status` reports it as `ok` when it exited 0. Logs and config live in named volumes (`airflow-logs`, `airflow-config`). `../dags` and `../plugins` are bind mounts, and Docker creates an empty `plugins/` at the repo root until S4 fills it.
- `stack up` passes `--build` (cached), and compose output goes to `logs/stack-up.log`. `tests/fixtures/compose_ps.json` is a real recorded `docker compose ps -a --format json` (NDJSON on this Docker Desktop).
- Measured at idle: six services at 1231 MB RAM; image 3078 MiB.
- The stack is left running for S2. accept_s1 passed (20/20 checks; 15 tests).

## Additions for S0
- The stack must run on Docker Desktop for Windows; scripts are PowerShell 7 (`pwsh`). Amir's laptop: check RAM headroom before starting other stacks (lineage-lab's OpenMetadata is heavy; stop it if `docker stats` shows pressure).
- The governor side (A1) is a separate plan in `../governor-airflow`; never touch it from this repo.

## Additions for S1
S1 adds image/, stack/, and stack.py. Keep pyproject free of apache-airflow; host dependencies stay pyyaml and pytest. The editable install points at src/, so python -m airflow_platform works. load(path) and validate(raw, base_dir) are done: DagSource.local is an absolute Path, git is a raw dict or None, and View and TaskLink are optional. render_bundles(projects, target='local') and render_compose_override(projects) raise NotImplementedError until S3. S3's signatures return list[dict] and dict, and the compose function takes registry_dir; update tests/test_projects.py::test_render_is_stubbed_until_s3 when replacing the stubs. projects/projects.yaml has only examples, with dags.local ../dags/examples. dags/examples/ contains .gitkeep only; hello_workload.py is S2. stack/.env.generated and stack/compose.projects.yaml are already gitignored. .terraform.lock.hcl is meant to be committed. Offline tests stay in tests/ and must not import Airflow.

## S1 result
*Airflow image and the lean local stack, 13 Nov 2026 19:05.*

Implementer `claude-tc-opus`; reviewers `cursor-grok`: pass; 0 fix loop(s); branch `factory/S1`.

| check | ok | detail |
|---|---|---|
| compose names its official source | yes | # Source: https://airflow.apache.org/docs/apache-airflow/3.3.2/docker-compose.yaml (downloaded 2026-11-13) |
| compose has no redis | yes |  |
| compose has no airflow-worker | yes |  |
| compose has no flower | yes |  |
| compose has no CeleryExecutor | yes |  |
| LocalExecutor | yes |  |
| Dockerfile uses apache/airflow 3.3 python3.12 | yes |  |
| providers installed with constraints | yes |  |
| requirements are providers only | yes |  |
| versions.yaml records the version | yes |  |
| no secrets in repo files | yes |  |
| status prints JSON | yes | {"up": true, "services": {"airflow-apiserver": "healthy", "airflow-dag-processor": "healthy", "airflow-init": "ok", "air |
| stack up | yes | {'airflow-apiserver': 'healthy', 'airflow-dag-processor': 'healthy', 'airflow-init': 'ok', 'airflow-scheduler': 'healthy |
| airflow 3.3.x | yes | 3.3.2 |
| five airflow services + postgres | yes | airflow-apiserver,airflow-dag-processor,airflow-init,airflow-scheduler,airflow-triggerer,postgres |
| all services healthy | yes | {'airflow-apiserver': 'healthy', 'airflow-dag-processor': 'healthy', 'airflow-init': 'ok', 'airflow-scheduler': 'healthy |
| stack under 3 GB RAM | yes | 1232 MB |
| image built | yes | 3228429877 |
| pytest tests | yes | 15 passed in 0.29s |
| required tests present | yes | 5 found |

Review: S1 matches the prompt. compose.yaml records the official 3.3.2 URL and download date 2026-11-13, and is trimmed to LocalExecutor with postgres, init, api-server, scheduler, dag-processor, and triggerer. Redis, worker, flower, and Celery are gone. Each service has a healthcheck. The Dockerfile is apache/airflow:3.3.2-python3.12 and installs only the five providers through constraints-3.12.txt. .env.example has the documented local defaults, including the FAB admin login. Live status was up, Airflow 3.3.2, six services healthy or ok, 1232 MB.

For Amir: Open questions in NOTES match the files: FAB auth manager rather than Simple, and no CLOUD_PROVIDERS arg. The local image is 3078 MiB; amazon and google are already in apache/airflow:3.3.2-python3.12, and the spec does not allow a slim base. 3.4.0 exists on PyPI; this step stays on 3.3.2. airflow-init's healthcheck command is true; dependents wait for service_completed_successfully, and live status reported init as ok.

## Additions for S2
The stack is left running for S2: compose project airflow_platform, Airflow 3.3.2, image airflow-platform:local, UI http://localhost:8080 via AIRFLOW_PORT. LocalExecutor. No redis, worker, flower, or docker socket. status sets up to false if any service is missing from the healthy/ok set; only airflow-init may be ok (exited 0). docker-proxy must have a real healthcheck. Auth is FabAuthManager, not SimpleAuthManager. Admin user is the documented airflow/airflow pair. JWT fallback in compose is airflow_jwt_secret. Confirm POST /auth/token on this server's /docs; do not assume the Simple auth route. up copies stack/.env.example to stack/.env if needed, then compose up -d --build --wait. It does not render; those functions still raise NotImplementedError, and compose.projects.yaml is added only when the file exists. DAGs mount from the repo dags/ directory. plugins/ may already be an empty directory. Logs and config are volumes airflow-logs and airflow-config. Providers in requirements.txt are unpinned and installed only with constraints-3.3.2/constraints-3.12.txt. They are already in the base image. Do not pip-install dbt, pandas, streamlit, langchain, or governor. No CLOUD_PROVIDERS build arg. Host tests stay offline and must not import Airflow.
