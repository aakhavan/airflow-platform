# NOTES

## Current state
S1 and S2 are in place and accept_s2 passed. Project airflow_platform runs Airflow 3.3.2 with the FAB auth manager and the documented admin login, LocalExecutor, Postgres 16, api-server, scheduler, dag-processor, triggerer, init, and docker-proxy. The proxy is tecnativa/docker-socket-proxy:v0.4.1 with only CONTAINERS, IMAGES, and POST; the raw socket is mounted read-only on that service alone. hello_workload runs airflow-platform/hello:local through tcp://docker-proxy:2375. A live run succeeded and the workload JSON line is in the task log. stack trigger, wait, and logs use REST API v2; the token from POST /auth/token stays in memory. status reports import_errors 0. The image still contains pandas because the google provider requires it; the 13 Nov relock took pandas off the denylist and probes packages with python -m pip. Bundle rendering is still the S3 stub, and the repo dags/ directory stays bind-mounted until S3 replaces it.

## Open questions
- S1 verify (auth manager): the official 3.3.2 compose file uses the **FAB auth manager** (`airflow.providers.fab.auth_manager.fab_auth_manager.FabAuthManager`), not Simple as spec §4 assumed. Its documented local admin login is `_AIRFLOW_WWW_USER_USERNAME` / `_AIRFLOW_WWW_USER_PASSWORD` = airflow / airflow, created by airflow-init. We kept FAB.
- S1 image size: airflow-platform:local is 3.23 GB, above the 2.5 GB line. All five providers (docker, standard, git, amazon, google) and fab are already preinstalled in `apache/airflow:3.3.2-python3.12` at the constrained versions, and our layer adds about 5 MB. A `CLOUD_PROVIDERS` switch would not shrink anything, so none was added. Only a `-slim` base would, and the spec doesn't allow one.
- S1: Airflow 3.4.0 is already on PyPI. The plan pins 3.3.x, so we use 3.3.2, the latest 3.3 patch.
- **S2 blocker (isolation check, needs a human decision):** `pandas` 3.0.5 is in `airflow-platform:local`. It comes from the official base image `apache/airflow:3.3.2-python3.12`, where `pip show pandas` gives "Required-by: apache-airflow-providers-google, apache-airflow-providers-snowflake, db-dtypes, pandas-gbq". It is a hard dependency of the google provider that spec §3 requires, so spec §3 (google provider) and the §5 denylist (pandas) contradict each other. The other five denylist names are absent. The options all touch `image/` or `plan/`, which S2 may not edit: (a) drop `apache-airflow-providers-google` and uninstall the preinstalled google/snowflake providers plus pandas in `image/Dockerfile`; (b) take pandas off the denylist as "allowed when a provider pulls it in"; (c) build on a slim base with no google provider.
- **S2 (acceptance probe):** `docker run --entrypoint pip airflow-platform:local list` exits 126 with "bash: /root/bin/pip: Permission denied". The stock base image does the same: its PATH starts with `/root/bin`, which holds a root-only pip guard script, and `/root` is mode 700 for user 50000. `--entrypoint /home/airflow/.local/bin/pip` works. The fix would be an `image/` change, e.g. `ENV PATH=/home/airflow/.local/bin:/usr/python/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin`. That is outside S2's paths, so it is not made.
- S2 verify (token route): the core `/openapi.json` has only `/api/v2/auth/login|logout`. The FAB auth manager serves its own app under `/auth` (`/auth/openapi.json`), where `POST /auth/token` takes `{"username","password"}` and returns 201 `{"access_token"}`. There is also `POST /auth/token/cli`. The spec's route holds with FAB.
- S2 verify (proxy sections): `CONTAINERS=1 IMAGES=1 POST=1` (plus the image's default `PING`/`VERSION`) is enough for DockerOperator with `force_pull=False`, `mount_tmp_dir=False` and `auto_remove="success"`. Nothing else was needed. IMAGES is needed because the operator lists images before deciding to pull.

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

- 13 Nov 19:42 (Claude via chat): S2 relock_resume: isolation check: pandas removed from the denylist (it is a google-provider dependency shipped in the official base image, not project code); pip probed via python -m pip (base image PATH guard). Fixture: replaced a log path the secret scanner flagged as high-entropy with a placeholder.

## S2 result
*Workload pattern (socket proxy, hello workload, trigger and wait), 13 Nov 2026 19:46.*

Implementer `claude-tc-opus`; reviewers `cursor-grok`: pass; 0 fix loop(s); branch `factory/S2`.

| check | ok | detail |
|---|---|---|
| docker-proxy service | yes |  |
| raw socket mounted only once | yes | 1 mounts |
| DAGs import only airflow/providers/stdlib | yes |  |
| hello workload exists | yes |  |
| no secrets in repo files | yes |  |
| pip list in airflow image | yes | zipp==4.1.0 | zope.event==6.2 | zope.interface==8.6 |
| no project libraries in airflow image | yes |  |
| no DAG import errors | yes | 0 |
| trigger hello_workload | yes | manual__2026-11-13T18:41:12.361785+00:00 |
| hello_workload run succeeded | yes | {'dag_id': 'hello_workload', 'run_id': 'manual__2026-11-13T18:41:12.361785+00:00', 'state': 'success', 'timed_out': Fals |
| workload JSON line in task log | yes | :group::Post Execute
Pushing xcom
::endgroup::
{"dag_id": "hello_workload", "run_id": "manual__2026-11-13T18:41:12.36178 |
| pytest tests | yes | 20 passed in 0.97s |
| required tests present | yes | 4 found |

Review: S2 matches the prompt, and the passing accept_s2 run is real. The Docker socket is one read-only mount on docker-proxy (tecnativa/docker-socket-proxy:v0.4.1, CONTAINERS/IMAGES/POST, no host port), recorded in NOTES; compose ps shows that service healthy. hello_workload imports only Airflow. The live run succeeded and the workload JSON line is in the task log. trigger and wait print one JSON line; the token stays in memory. Isolation passes after the 13 Nov relock, which dropped pandas and uses python -m pip.

For Amir: Spec section 5 still names pandas on the isolation denylist. The 13 Nov relock removed it, because the official image installs pandas for the google provider, and switched the probe to python -m pip. NOTES Current state still says accept_s2 fails; that sentence is from before the relock. No code change is required.

## Additions for S3
S3 replaces the repo dags/ bind mount with LocalDagBundle mounts. hello_workload.py is at dags/examples/hello_workload.py and must keep loading. docker-proxy is in stack.EXPECTED, so status.up requires it healthy. The Docker socket stays mounted only on docker-proxy, with CONTAINERS=1, IMAGES=1, POST=1. stack up builds each workloads/<name> image as airflow-platform/<name>:local before compose; those images are not compose services. trigger, wait, and logs already exist. The token is POST /auth/token on the FAB app (the core OpenAPI only has /api/v2/auth/login|logout) and stays unprinted. DAGs start paused, so trigger sends PATCH is_paused false, then POST dagRuns with logical_date null. Inside the Airflow image, pip is python -m pip. pandas stays installed for the google provider and is off the denylist. render_bundles and render_compose_override still raise NotImplementedError. projects.yaml has only examples.
