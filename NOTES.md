# NOTES

## Current state
S3 is in place and accept_s3 passed on 13 Nov. The stack is Airflow 3.3.2 with FAB auth, LocalExecutor, Postgres, the api-server, scheduler, dag-processor, triggerer, and docker-proxy, and it was left running on the real registry. DAGs load only as LocalDagBundle entries rendered from projects/projects.yaml: hello_workload is in bundle examples, and the repo dags/ mount is gone. stack up, which scripts/up.ps1 calls, writes git-ignored stack/.env.generated and stack/compose.projects.yaml, then Compose uses both env files. The api-server, scheduler, dag-processor, and triggerer each get a read-only mount of every project at /opt/airflow/projects/<name> and of the registry at /opt/airflow/projects/projects.yaml. GitDagBundle is rendered only for target cloud and is unit-tested, not run live. pandas remains in the image for the google provider and is off the isolation denylist.

## Open questions
- S1 verify (auth manager): the official 3.3.2 compose file uses the **FAB auth manager** (`airflow.providers.fab.auth_manager.fab_auth_manager.FabAuthManager`), not Simple as spec §4 assumed. Its documented local admin login is `_AIRFLOW_WWW_USER_USERNAME` / `_AIRFLOW_WWW_USER_PASSWORD` = airflow / airflow, created by airflow-init. We kept FAB.
- S1 image size: airflow-platform:local is 3.23 GB, above the 2.5 GB line. All five providers (docker, standard, git, amazon, google) and fab are already preinstalled in `apache/airflow:3.3.2-python3.12` at the constrained versions, and our layer adds about 5 MB. A `CLOUD_PROVIDERS` switch would not shrink anything, so none was added. Only a `-slim` base would, and the spec doesn't allow one.
- S1: Airflow 3.4.0 is already on PyPI. The plan pins 3.3.x, so we use 3.3.2, the latest 3.3 patch.
- **S2 blocker (isolation check, needs a human decision):** `pandas` 3.0.5 is in `airflow-platform:local`. It comes from the official base image `apache/airflow:3.3.2-python3.12`, where `pip show pandas` gives "Required-by: apache-airflow-providers-google, apache-airflow-providers-snowflake, db-dtypes, pandas-gbq". It is a hard dependency of the google provider that spec §3 requires, so spec §3 (google provider) and the §5 denylist (pandas) contradict each other. The other five denylist names are absent. The options all touch `image/` or `plan/`, which S2 may not edit: (a) drop `apache-airflow-providers-google` and uninstall the preinstalled google/snowflake providers plus pandas in `image/Dockerfile`; (b) take pandas off the denylist as "allowed when a provider pulls it in"; (c) build on a slim base with no google provider.
- **S2 (acceptance probe):** `docker run --entrypoint pip airflow-platform:local list` exits 126 with "bash: /root/bin/pip: Permission denied". The stock base image does the same: its PATH starts with `/root/bin`, which holds a root-only pip guard script, and `/root` is mode 700 for user 50000. `--entrypoint /home/airflow/.local/bin/pip` works. The fix would be an `image/` change, e.g. `ENV PATH=/home/airflow/.local/bin:/usr/python/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin`. That is outside S2's paths, so it is not made.
- S2 verify (token route): the core `/openapi.json` has only `/api/v2/auth/login|logout`. The FAB auth manager serves its own app under `/auth` (`/auth/openapi.json`), where `POST /auth/token` takes `{"username","password"}` and returns 201 `{"access_token"}`. There is also `POST /auth/token/cli`. The spec's route holds with FAB.
- S2 verify (proxy sections): `CONTAINERS=1 IMAGES=1 POST=1` (plus the image's default `PING`/`VERSION`) is enough for DockerOperator with `force_pull=False`, `mount_tmp_dir=False` and `auto_remove="success"`. Nothing else was needed. IMAGES is needed because the operator lists images before deciding to pull.
- S3 verify (DAG bundles): WebFetch of the 3.3 docs was denied in this session, and no Airflow source is on the host, so the facts below come from the Airflow 3.x "DAG bundles" docs as known and were **confirmed on the running 3.3.2 stack**. `GET /api/v2/dags` shows `hello_workload` with `bundle_name: examples`, and import_errors is 0. Config: `[dag_processor] dag_bundle_config_list` (env `AIRFLOW__DAG_PROCESSOR__DAG_BUNDLE_CONFIG_LIST`), a JSON list of `{"name","classpath","kwargs"}`; the default is one `dags-folder` LocalDagBundle, which our list replaces. `LocalDagBundle` = `airflow.dag_processing.bundles.local.LocalDagBundle`, kwargs `path` (+ base `refresh_interval`). `GitDagBundle` = `airflow.providers.git.bundles.git.GitDagBundle` (git provider), kwargs `tracking_ref` (required), `subdir`, `git_conn_id`, `repo_url`, `refresh_interval`. Unit-tested only, never run live. Readers: the dag-processor parses; the scheduler runs tasks with LocalExecutor (workers need the bundle); the triggerer; and the api-server instantiates bundles for view URLs. All four get the env var and the read-only mounts. The git kwargs were not checked against the provider source.
- S3 verify (multiple env files): `docker compose --env-file stack/.env --env-file stack/.env.generated` reads both, a later file winning on duplicates (Compose v2). This was confirmed live: the override's `${AIRFLOW__DAG_PROCESSOR__DAG_BUNDLE_CONFIG_LIST:?...}` guard would abort compose if the second file were ignored, and up succeeded with the examples bundle loaded.

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

## S3 notes (implementer)
- `stack render [--projects PATH] [--target local|cloud]` writes `stack/.env.generated` (one single-quoted, literal JSON value) and `stack/compose.projects.yaml`. `up` renders first. `compose_args` adds the override plus both `--env-file`s only when both generated files exist.
- The override adds, for apiserver, scheduler, dag-processor and triggerer: `<abs posix path>:/opt/airflow/projects/<name>:ro` per project, the registry file at `/opt/airflow/projects/projects.yaml:ro` (for the S4 plugin), and `AIRFLOW__DAG_PROCESSOR__DAG_BUNDLE_CONFIG_LIST: ${...:?}`. The repo `dags/` mount is gone.
- `render_compose_override(projects, registry_dir, registry_file="projects.yaml")`: the extra file name lets a registry with a different file name (the acceptance's `logs/tmp_projects.yaml`) mount correctly.
- `status --dags` adds `dag_ids` and `dag_bundles` ({dag_id: bundle_name}, stale DAGs skipped); `status` also lists `projects` from the registry.

## S3 result
*projects.yaml to DAG bundles and the compose override, 13 Nov 2026 20:08.*

Implementer `claude-tc-opus`; reviewers `cursor-grok`: pass; 0 fix loop(s); branch `factory/S3`.

| check | ok | detail |
|---|---|---|
| generated files ignored | yes |  |
| S2 temporary dags mount removed | yes |  |
| no secrets in repo files | yes |  |
| stack up with bundles | yes | {"command": "up", "ok": true, "env_created": false, "projects": ["examples"], "workloads": ["airflow-platform/hello:loca |
| trigger hello_workload | yes | manual__2026-11-13T18:58:26.717366+00:00 |
| hello_workload run succeeded | yes | {'dag_id': 'hello_workload', 'run_id': 'manual__2026-11-13T18:58:26.717366+00:00', 'state': 'success', 'timed_out': Fals |
| up with a third project | yes | {"command": "up", "ok": true, "env_created": false, "projects": ["examples", "tmp-project"], "workloads": ["airflow-plat |
| new project's DAG loaded | yes |  |
| back to the real registry | yes | {"command": "up", "ok": true, "env_created": false, "projects": ["examples"], "workloads": ["airflow-platform/hello:loca |
| registry file untouched by the test | yes |  |
| pytest tests | yes | 25 passed in 0.34s |
| required tests present | yes | 5 found |

Review: S3 matches the prompt, and accept_s3's pass is a real stack run. up.ps1 calls stack up, which renders git-ignored stack/.env.generated and stack/compose.projects.yaml and passes both env files to compose. LocalDagBundle classpath and path were confirmed on Airflow 3.3.2 (hello_workload, bundle examples). Git kwargs are recorded and unit-tested only. Mounts are :ro on apiserver, scheduler, dag-processor, and triggerer. The S2 dags mount is gone. A third project outside the repo loaded with no code change.

For Amir: The docs fetch was denied in the implementer session. LocalDagBundle was checked on the running 3.3.2 server, not only from memory. GitDagBundle kwargs were not checked against the provider source. accept_s3.py treats the new DAG as loaded when its id appears; it does not assert bundle_name tmp-project. The probe DAG lives only under logs/tmp_project, so the mount and bundle config did run.

## Additions for S4
S4 adds the project views plugin. The registry is already mounted read-only at /opt/airflow/projects/projects.yaml on airflow-apiserver, airflow-scheduler, airflow-dag-processor, and airflow-triggerer. plugins/ is already bind-mounted at /opt/airflow/plugins from the repo, but that mount is writable; the S4 prompt asks for read-only. Do not pip-install the host package into the image. Copy the views logic into the plugin; yaml is already in the Airflow image. examples in projects.yaml has no view or task_link yet; the live check adds both, aimed at http://localhost:8080/docs. Trigger hello_workload (bundle examples, task hello). DAGs are paused at creation; stack trigger unpauses. status --dags returns dag_ids and dag_bundles from GET /api/v2/dags, skipping stale DAGs. The auth token is POST /auth/token on the FAB app and must stay unprinted. On a bad projects.yaml the plugin logs one warning and registers nothing. Record the 3.3 external_views keys, whether a dag tab can be limited, the get_link signature, and the plugins route. Set AIRFLOW__CORE__LAZY_LOAD_PLUGINS false only if the docs say UI plugins need it. Git bundles are not live. The stack is left up on the real registry.
