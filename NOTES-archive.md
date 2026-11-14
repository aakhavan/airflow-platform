# NOTES archive

Sections rotated out of NOTES.md (PLAN.md §7.4), oldest first.

## Relocks
- 13 Nov 2026 18:40: S0/S6/S9 allowed_paths gaps; uv-run command rule in prompts (Claude via chat) (changed: plan.yaml, plan/prompts/S0.md, plan/prompts/S1.md, plan/prompts/S10.md, plan/prompts/S2.md, plan/prompts/S3.md, plan/prompts/S4.md, plan/prompts/S5.md, plan/prompts/S6.md, plan/prompts/S7.md, plan/prompts/S8.md, plan/prompts/S9.md)

## S0 result
*Scaffold, uv tooling and the projects loader skeleton, 13 Nov 2026 18:48.*

Implementer `claude-tc-opus`; reviewers `cursor-grok`: pass; 0 fix loop(s); branch `factory/S0`.

| check | ok | detail |
|---|---|---|
| pyproject exists | yes |  |
| no apache-airflow in pyproject | yes |  |
| pyyaml dependency | yes |  |
| .gitignore has .env | yes |  |
| .gitignore has !.env.example | yes |  |
| .gitignore has stack/.env.generated | yes |  |
| .gitignore has stack/compose.projects.yaml | yes |  |
| .gitignore has logs/ | yes |  |
| .gitignore has .terraform/ | yes |  |
| .gitignore has .factory/ | yes |  |
| .tfstate ignored | yes |  |
| .gitattributes eol=lf | yes |  |
| projects.yaml exists | yes |  |
| CONTEXT.md and 3 ADRs present | yes |  |
| no secrets in repo files | yes |  |
| pytest tests | yes | 7 passed in 0.29s |
| required tests present | yes | 5 found |

Review: S0 matches its prompt. The uv project is Python 3.12 with pyyaml 6.0.3 and pytest 9.2.0; the lockfile contains no Airflow package. Gitignore covers .env, .env.*, !.env.example, stack/.env.generated, stack/compose.projects.yaml, logs/, *.tfstate*, .terraform/, and .factory/; .terraform.lock.hcl stays tracked. projects.py only reads YAML and the filesystem. load resolves dags.local against the YAML directory, and errors name the project and the field. The five required tests cover those rules. Render stubs raise NotImplementedError. The acceptance pass matches the files.

For Amir: NOTES.md S0 result still says uv.lock is missing and acceptance was not run. uv.lock is present and accept_s0 reported 7 passed in 0.29s. The plan.yaml and plan/prompts edits in the step diff are the 18:40 relock (S0 allowed_paths includes dags/; uv-run command rule), not loader code. STATUS.md still shows the earlier scope_violation stop from run 20261113-183318.

## Relocks
- 13 Nov 2026 19:40: isolation check: pandas removed from the denylist (it is a google-provider dependency shipped in the official base image, not project code); pip probed via python -m pip (base image PATH guard). Fixture: replaced a log path the secret scanner flagged as high-entropy with a placeholder. (via supervise, by Claude via chat (delegated by Amir)) (changed: plan/accept/_common.py, plan/accept/accept_s2.py)

## S1 result (implementer notes)
- Airflow **3.3.2** (`image/Dockerfile`, one `ARG AIRFLOW_VERSION`). Providers are installed with the official constraints-3.3.2/constraints-3.12.txt. `stack/compose.yaml` is the official 3.3.2 file, trimmed: LocalExecutor, no broker/worker/flower/cli, LOAD_EXAMPLES false, port `${AIRFLOW_PORT:-8080}`, and healthchecks everywhere.
- Auth manager: FAB, admin login airflow/airflow (the documented default, only in `stack/.env.example`).
- `airflow-init` is one-shot: `status` reports it as `ok` when it exited 0. Logs and config live in named volumes (`airflow-logs`, `airflow-config`). `../dags` and `../plugins` are bind mounts, and Docker creates an empty `plugins/` at the repo root until S4 fills it.
- `stack up` passes `--build` (cached), and compose output goes to `logs/stack-up.log`. `tests/fixtures/compose_ps.json` is a real recorded `docker compose ps -a --format json` (NDJSON on this Docker Desktop).
- Measured at idle: six services at 1231 MB RAM; image 3078 MiB.
- The stack is left running for S2. accept_s1 passed (20/20 checks; 15 tests).

## S2 result (implementer notes)
- `docker-proxy`: `tecnativa/docker-socket-proxy:v0.4.1` (in versions.yaml), env `CONTAINERS=1 IMAGES=1 POST=1`, no host port, healthcheck `wget http://127.0.0.1:2375/_ping`. The host socket is mounted read-only at `/run/docker.sock` inside the proxy with `SOCKET_PATH=/run/docker.sock`. The different target path keeps the socket path appearing exactly once in compose.yaml, which accept_s2 requires. No Airflow service mounts the socket. `docker-proxy` is now in `stack.EXPECTED`.
- `workloads/hello` (`python:3.12.12-slim`, runs as nobody) prints the greeting and `{"workload":"hello","ok":true,"python":"3.12.12"}`. `stack up` runs `docker build` for every `workloads/<name>/Dockerfile` as `airflow-platform/<name>:local` before compose up (logs in `logs/workload-<name>.log`).
- `dags/examples/hello_workload.py`: DockerOperator `hello`. `docker_url` comes from `Variable.get("docker_url", default="tcp://docker-proxy:2375")` at parse time. Item 4 needed no new mount, because S1 already bind-mounts the repo's `dags/` at `/opt/airflow/dags`, so `dags/examples/` loads from there (log: "Filling up the DagBag from /opt/airflow/dags/examples/hello_workload.py"). S3 replaces this with bundles.
- `stack.py`: `trigger` first unpauses the DAG (`PATCH /api/v2/dags/{id}` `is_paused=false`, because DAGs are paused at creation), then sends `POST /api/v2/dags/{id}/dagRuns` with `{"logical_date": null, "conf": {...}}`. `wait` polls `GET .../dagRuns/{run_id}` every 3 s until success or failed. `logs` reads `.../taskInstances/{task}` for `try_number`, then `.../logs/{try}?full_content=true`, and prints the last 20 lines. The token comes from `POST /auth/token` with the `.env` admin (default airflow/airflow) and is held only in memory. `status` adds `import_errors` from `airflow dags list-import-errors -o json` in the scheduler, which prints `[]` (verified); the value is -1 if the CLI can't be reached.
- Fixtures: `tests/fixtures/api_v2_hello.json` holds real trigger, run, task-instance and log responses, with ids, UUIDs and hostnames removed. `compose_ps.json` was re-recorded with docker-proxy.
- accept_s2: 11 of 12 checks pass, including the live run and the JSON line in the task log. `pip list in airflow image` fails, see Open questions (pip PATH and pandas). 20 tests pass.

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

## S3 notes (implementer)
- `stack render [--projects PATH] [--target local|cloud]` writes `stack/.env.generated` (one single-quoted, literal JSON value) and `stack/compose.projects.yaml`. `up` renders first. `compose_args` adds the override plus both `--env-file`s only when both generated files exist.
- The override adds, for apiserver, scheduler, dag-processor and triggerer: `<abs posix path>:/opt/airflow/projects/<name>:ro` per project, the registry file at `/opt/airflow/projects/projects.yaml:ro` (for the S4 plugin), and `AIRFLOW__DAG_PROCESSOR__DAG_BUNDLE_CONFIG_LIST: ${...:?}`. The repo `dags/` mount is gone.
- `render_compose_override(projects, registry_dir, registry_file="projects.yaml")`: the extra file name lets a registry with a different file name (the acceptance's `logs/tmp_projects.yaml`) mount correctly.
- `status --dags` adds `dag_ids` and `dag_bundles` ({dag_id: bundle_name}, stale DAGs skipped); `status` also lists `projects` from the registry.

## Relocks
- 13 Nov 2026 21:07: S5 .env.example quoting + S10 README secrets section (Claude via chat) (changed: plan/prompts/S10.md)
- 13 Nov 2026 21:40: verdict_stop fix: {run_id_safe} placeholder so the task link matches the profile file stem; runbook --dsn + worktree .env; accept_s5 checks the stem in the link (via supervise, by Claude via chat (delegated by Amir)) (changed: plan.yaml, plan/accept/accept_s5.py, plan/prompts/S5.md)

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

## S4 notes (implementer)
- `src/airflow_platform/views.py` (pure, stdlib): `registry_errors`, `views_for`, `link_for` (+ `_get`, which reads dicts or `projects.Project`). The functions between the COPY markers are copied verbatim into `plugins/project_views/__init__.py`; `test_plugin_copy_matches_views_module` compares them by AST source segment.
- Per project with a `view`: a nav entry (`category: browse`, `url_route: <name>`) and a dag tab (`url_route: <name>-dag`). Both set `url_route`, so the UI iframes the page. Per project with a `task_link`: one `ProjectTaskLink_<name>` in `global_operator_extra_links`; it returns `""` for DAGs outside `dag_prefix`.
- The plugin reads `PLATFORM_PROJECTS_FILE` or `/opt/airflow/projects/projects.yaml`. It does no host-path checks, because those paths don't exist in the container. On any read or validation error it logs one warning and registers nothing.
- `plugins/` is mounted `:ro` on every Airflow service. airflow-init's `chown -R /opt/airflow` can't change it; that does not fail init, and `up` passed.
- `stack plugins` prints the paged `GET /api/v2/plugins` as one line. `stack links <dag> <run> <task>` prints `{"links": {...}, "source": "api"}`.
- `projects.yaml`: `examples` now has `view` (Examples, http://localhost:8080/docs) and `task_link` (Open docs, `...docs?run_id={run_id}`, prefix `hello_`). S5 replaces this with governor's entry.
- Live, 13 Nov: `accept_s4` passed. The plugin is loaded with 2 views and 1 global link. The hello_workload run's link is `http://localhost:8080/docs?run_id=manual__2026-11-13T19%3A14%3A22.354427%2B00%3A00`. 36 tests pass. The stack is left up on the real registry.

## S4 result
*Project views plugin (external views and task links), 13 Nov 2026 20:18.*

Implementer `claude-tc-opus`; reviewers `claude-tc-fable`: pass; 0 fix loop(s); branch `factory/S4`.

| check | ok | detail |
|---|---|---|
| plugin exists | yes |  |
| plugin has no fastapi_apps | yes |  |
| plugin has no react_apps | yes |  |
| plugin has no flask | yes |  |
| plugin has no appbuilder | yes |  |
| plugin uses global_operator_extra_links | yes |  |
| no secrets in repo files | yes |  |
| stack up with plugin | yes | {"command": "up", "ok": true, "env_created": false, "projects": ["examples"], "workloads": ["airflow-platform/hello:loca |
| stack plugins prints JSON | yes | {"plugins": [{"name": "OpenLineageProviderPlugin", "macros": [], "flask_blueprints": [], "fastapi_apps": [], "fastapi_ro |
| project_views plugin loaded | yes | {"plugins": [{"name": "OpenLineageProviderPlugin", "macros": [], "flask_blueprints": [], "fastapi_apps": [], "fastapi_ro |
| examples nav view registered | yes | {"plugins": [{"name": "OpenLineageProviderPlugin", "macros": [], "flask_blueprints": [], "fastapi_apps": [], "fastapi_ro |
| trigger hello_workload | yes | manual__2026-11-13T19:16:37.574698+00:00 |
| hello_workload run succeeded | yes | {'dag_id': 'hello_workload', 'run_id': 'manual__2026-11-13T19:16:37.574698+00:00', 'state': 'success', 'timed_out': Fals |
| task link resolves for the run | yes | {'links': {'Open docs': 'http://localhost:8080/docs?run_id=manual__2026-11-13T19%3A16%3A37.574698%2B00%3A00'}, 'source': |
| pytest tests | yes | 36 passed in 0.45s |
| required tests present | yes | 7 found |

Review: S4 delivers the project_views plugin (external_views nav+dag tab, one BaseOperatorLink per task_link via global_operator_extra_links), a pure views.py with an AST-verified copy in the plugin, a read-only plugins mount, projects.yaml view/task_link on examples, and stack plugins/links commands. Imports are stdlib+yaml+airflow only; a broken registry logs one warning and registers nothing; links use only run_id/dag_id/task_id, are quoted, and are empty for other DAGs. The per-DAG tab finding is recorded honestly. Acceptance passed live with the link resolved via the REST API.

For Amir: The docs fetch was denied again, so the 3.3 plugin facts in NOTES come from the live server's /openapi.json rather than the docs text; they were confirmed working live. The acceptance's 'nav view registered' check only greps for the href, so it would not catch a wrong destination; unit tests cover that.

## Additions for S5
S5 replaces the examples view/task_link in projects/projects.yaml with governor's entry (view http://localhost:8501, task_link url_template with {run_id}, dag_prefix governor_). The plugin reads /opt/airflow/projects/projects.yaml inside the container, validates only name/view/task_link (no host path checks), and builds views at import time, so a registry change needs a stack restart to show up. url_template may use only run_id, dag_id and task_id; anything else makes the whole plugin register nothing with one warning. The dag tab appears on every DAG (3.3 has no per-DAG filter key). Link class names are ProjectTaskLink_<name> with non-alphanumerics replaced by underscores. plugins/ is mounted :ro on all Airflow services; airflow-init's chown on it is harmless. stack plugins and stack links <dag> <run> <task> exist; links returns {'links': {...}, 'source': 'api'}. plugins/, src/airflow_platform/views.py and tests/test_views.py are untracked and must be git-added with the S4 commit.

## S5 notes (implementer)
- `projects.yaml`: examples' S4 placeholder view/link removed; `governor` added as §6 (worktree path, documented `git` entry, view `http://localhost:8501`, link `http://localhost:8501/Profiles?run_id={run_id}`, prefix `governor_`). The path `/Profiles` comes from A1's `apps/streamlit/pages/4_Profiles.py`, which reads `st.query_params.get("run_id")`.
- `stack/.env.example`: the 7 `AIRFLOW_VAR_*` the DAG reads (`docker_url`, `governor_data_volume`, `governor_pg_host/port/db`, `governor_build_user/password`), with defaults from governor's `testbed/README.md` and `testbed/apply_roles.py` (`governor_build_local`).
- `stack/.env` existed and was byte-identical to the old `.env.example` (checked with `cmp`, never read), so I deleted it and `stack up` recreated it with the new lines. The runbook tells users with an edited `.env` to copy the lines across.
- Tests: new `tests/test_governor.py` (3 required tests; the page-name sub-check skips when `../governor-airflow` is absent). `test_projects.py` now expects `["examples", "governor"]`. 39 passed. Note for S6: `projects.load` on the repo registry checks that `../../governor-airflow/airflow/dags` exists, so the two repo-registry assertions in `test_projects.py` will fail in CI without the worktree.
- Live, 13 Nov: `stack up` is ok, `status --dags` lists `governor_profile_raw` (bundle governor) and 0 import errors, and the plugin registers both 8501 views plus `ProjectTaskLink_governor`.

## S5 blocked: preconditions
`accept_s5` fails only its preconditions: the governor api (8000/health) and ui (8501/_stcore/health) are not running. The worktree, `governor:local` and the test bed on 55432 are fine. The live part (trigger, profile file, link 200) did not run. I may not start governor containers, so that is for Amir: `docker compose up -d --wait` in `../governor-airflow`, then rerun `uv run python plan/accept/accept_s5.py`.

## Relocks
- 14 Nov 2026 01:33: acceptance bug: terraform test check matched 'fail' in '0 failed'; now parses the counts (via supervise, by Claude via chat (delegated by Amir)) (changed: plan/accept/_tf.py)

## S5 result
*Governor as the first project, end to end, 14 Nov 2026 00:27.*

Implementer `claude-tc-opus`; reviewers `claude-tc-fable`: pass, `cursor-grok`: pass; 2 fix loop(s); branch `factory/S5`.

| check | ok | detail |
|---|---|---|
| governor worktree exists | yes | C:\Users\amir0\portfolio\governor-airflow |
| governor:local image exists | yes | sha256:db07b35c5092cf0d2059021b97141f028c434af68e9f79ab984abade1228b56e |
| governor test bed up on 55432 | yes | testbed-postgres-1 |
| governor api healthy | yes |  |
| governor ui up | yes |  |
| governor in registry | yes |  |
| governor view + link | yes |  |
| runbook exists | yes |  |
| no secrets in repo files | yes |  |
| stack up with governor | yes | {"command": "up", "ok": true, "env_created": false, "projects": ["examples", "governor"], "workloads": ["airflow-platfor |
| trigger governor_profile_raw | yes | manual__2026-11-13T20:56:29.520836+00:00 |
| governor_profile_raw run succeeded | yes | {'dag_id': 'governor_profile_raw', 'run_id': 'manual__2026-11-13T20:56:29.520836+00:00', 'state': 'success', 'timed_out' |
| profile file written to governor volume | yes | governor-airflow_governor-data T20_41_50.106172+00_00.json
manual__2026-11-13T20_54_34.089290+00_00.json
manual__2026-11 |
| task link points at the governor UI | yes | {'links': {'Open report': 'http://localhost:8501/Profiles?run_id=manual__2026-11-13T20_56_29.520836%2B00_00'}, 'source': |
| task link carries the profile's file-safe run id | yes | http://localhost:8501/Profiles?run_id=manual__2026-11-13T20_56_29.520836%2B00_00 |
| report link answers 200 | yes | http://localhost:8501/Profiles?run_id=manual__2026-11-13T20_56_29.520836%2B00_00 |
| pytest tests | yes | 40 passed in 0.44s |
| required tests present | yes | 4 found |

Review: claude-tc-fable: pass | cursor-grok: pass

For Amir: Two things at the gate: (1) run `git -C ../governor-airflow status --short` and `git -C ../governor status --short` yourself; the reviewer sandbox blocked those calls, so 'nothing changed there' rests on indirect evidence. (2) The A1 commit is on factory/A1, not airflow-integration; fast-forward airflow-integration before merging to main, or the runbook's 'after the merge' section points at a branch without the DAG.

## Additions for S6
S6 (CI): tests/test_projects.py's two repo-registry assertions and tests/test_governor.py's page-name sub-check depend on ../governor-airflow existing; the latter skips, the former will fail in CI without the worktree (NOTES already flags it). Commit must git-add the untracked docs/projects/ and tests/test_governor.py. stack/.env.example values are now double-quoted (compose strips them; tests strip them too). url_template placeholders are run_id, run_id_safe, dag_id, task_id in projects.py, views.py and the plugin copy (keep identical; test_plugin_copy_matches_views_module). accept_s5 picks the first `docker volume ls` entry ending in governor-data; that is governor-airflow_governor-data by ASCII order, but a stale governor_governor-data volume from the earlier wrong-name run still exists and could be removed.

## S6 result
*CI for python and the local stack, 14 Nov 2026 00:50.*

Implementer `claude-tc-opus`; reviewers `cursor-grok`: pass; 0 fix loop(s); branch `factory/S6`.

| check | ok | detail |
|---|---|---|
| workflow exists | yes |  |
| python and stack jobs | yes |  |
| no secrets referenced | yes |  |
| actions pinned | yes | actions/checkout@v5,astral-sh/setup-uv@v6,actions/checkout@v5,astral-sh/setup-uv@v6,actions/upload-artifact@v4 |
| ci registry has only examples | yes |  |
| no secrets in repo files | yes |  |
| ci-local.ps1 passes | yes | stack wait: {"dag_id": "hello_workload", "run_id": "manual__2026-11-13T23:37:21.341506+00:00", "state": "success", "time |
| pytest tests | yes | 62 passed in 0.57s |
| required tests present | yes | 4 found |

Review: S6 matches the prompt. ci.yml (push, pull_request, ubuntu-latest, contents: read) has a python job (uv sync --frozen, pytest) and a stack job (up projects/ci.yaml, import_errors == 0, hello_workload success within 300s, logs on failure, always down -Volumes). Actions are checkout@v5, setup-uv@v6, upload-artifact@v4. No secrets. ci-local.ps1 ran that sequence on airflow_platform_ci:8081; acceptance showed success and volumes removed; 62 tests passed.

For Amir: ci-local.ps1 always calls down -Volumes, but it still exits 0 if that call fails. This run's down JSON was ok true with volumes_removed true, and the workflow down step fails the GitHub job on a non-zero exit. The acceptance output does not show the dev stack still running on 8080 beside port 8081. GitHub Actions itself has not run.

## S7 notes (implementer)
- Terraform is not on PATH on this host, so `plan/accept/_tf.py` ran everything in `hashicorp/terraform:1.13` (Docker). `required_version = "~> 1.13.0"`, `hashicorp/aws ~> 6.0` (locked 6.73.0); both are in `stack/versions.yaml`. `mock_provider`, `override_data` and assertions on `local.*` work on 1.13.
- **Acceptance blocker (needs a `plan/` fix):** fmt, init, validate (module + envs/aws), pytest (68 passed) and every static check pass, and `terraform test` prints `Success! 3 passed, 0 failed.`. But `_tf.py` line 32 fails the check because the text after the last "success" contains "fail" ("0 failed"), which Terraform always prints. Suggested fix: `re.search(r"(\d+) passed, 0 failed", r.stdout)`. I did not work around it.
- Secret names (default): `AIRFLOW__API_AUTH__JWT_SECRET`, `FERNET_KEY`, `_AIRFLOW_WWW_USER_PASSWORD`, the three stack/.env values that must not keep local defaults on a VM. Slots are `<name>/<KEY>` (`airflow-platform/<KEY>` by default). A slot with no value is skipped at boot and that key keeps the stack default, so a smoke test works with empty slots.
- The template takes one variable beyond the S7 list, `secret_prefix`. S8 must pass it; GCP slots are `<prefix>-<KEY>` because GCP secret IDs can't contain `/`.
- `AIRFLOW__SECRETS__BACKEND(_KWARGS)` is written to stack/.env (compose passes .env through `env_file`) with every prefix set to `null`. The role may read only its own slots, so Airflow lookups under `connections/`/`variables/` prefixes would be denied. Turning the prefixes on needs a wider policy, which is a human decision.
- In cloud-init the TTL `shutdown -h +N` runs first, not last, so a failed boot still terminates. `secret_recovery_window_days` (default 7, 0 for smoke) was added so re-applying after a destroy doesn't hit "scheduled for deletion". IMDS hop limit is 2, so containers can reach the role. `ignore_changes = [ami]`.
- `*.tfvars` is not in `.gitignore` (outside S7 paths); `test_no_tfvars_committed` guards it instead.

## Additions for S7
S7 is the AWS Terraform module and mock-provider tests. Leave .github/workflows/ci.yml without a terraform job and without secrets; the terraform job arrives in S9, and permissions stay contents: read. Pytest on a runner has no ../governor-airflow checkout: test_projects.py expects the repo registry to fail only on governor's missing dags.local, and test_governor.py skips only the Streamlit page-name check. The stack job renders projects/ci.yaml (examples only). Every python -m airflow_platform.stack subcommand takes --compose-project (default airflow_platform) and --port (AIRFLOW_PORT from stack/.env, else 8080). Any other compose project writes its generated env and override under logs/<project>/, not into stack/. The workflow has not executed on GitHub; scripts/ci-local.ps1 is the run that passed.

- 14 Nov 01:01 (Claude via chat): S7 secret_in_diff false positive on .terraform.lock.hcl provider hashes; added .terraform.lock.hcl to the factory scanner lockfile list (factory repo, uncommitted). resume.

- 14 Nov 01:34 (Claude via chat): S7 loops_exhausted was an acceptance bug: _tf.py matched "fail" in "0 failed". Now parses "N passed, M failed". relock_resume.

## S7 result
*Terraform module for AWS, tested with mock providers, 14 Nov 2026 01:44.*

Implementer `claude-tc-opus`; reviewers `cursor-grok`: pass; 2 fix loop(s); branch `factory/S7`.

| check | ok | detail |
|---|---|---|
| IMDSv2 required | yes |  |
| no 0.0.0.0/0 ingress | yes |  |
| TTL terminate wiring | yes |  |
| registry behind enable_registry | yes |  |
| no secret versions created | yes |  |
| no tfvars committed | yes |  |
| no backend block in envs/aws | yes |  |
| shared cloud-init template | yes |  |
| no secrets in repo files | yes |  |
| terraform fmt | yes |  |
| init terraform/modules/airflow-vm-aws | yes | If you ever set or change modules or backend configuration for Terraform, | rerun this command to reinitialize your work |
| validate terraform/modules/airflow-vm-aws | yes | Success! The configuration is valid. |
| init terraform/envs/aws | yes | If you ever set or change modules or backend configuration for Terraform, | rerun this command to reinitialize your work |
| validate terraform/envs/aws | yes | Success! The configuration is valid. |
| terraform test terraform/modules/airflow-vm-aws | yes | tests/main.tftest.hcl... pass |  | Success! 3 passed, 0 failed. |
| terraform/modules/airflow-vm-aws has a test file | yes |  |
| pytest tests | yes | 68 passed in 0.60s |
| required tests present | yes | 4 found |

Review: S7 matches the prompt and spec §9. Acceptance is trustworthy: terraform test ran 3 mock plan runs (3 passed) plus pytest. Ingress is empty, IMDSv2 is required, GetSecretValue covers only this module's secret ARNs, and no secret version exists. TTL uses terminate when ttl_minutes > 0 (else stop) and cloud-init adds shutdown -h +N only then. ECR count follows enable_registry, default false. No tfvars or backend is committed. templatefile passes names, prefix, repo, region and TTL, never secret values.

For Amir: Static acceptance checks are keyword scans (the ingress check splits on the first occurrence of egress). The plan asserts in tests/main.tftest.hcl are the real evidence. Those asserts do not read the IAM policy document; the least-privilege statement is only in main.tf. Cloud-init sets the Airflow secrets backend with all prefixes null, so connection and variable lookups stay off until someone widens the policy. IPv6 egress ::/0 is set on the security group; a default VPC has no IPv6 CIDR, and this was not applied.

## Additions for S8
S8 reuses terraform/templates/cloud-init.yaml.tftpl. Pass secret_prefix (extra variable beyond the S7 list): GCP secret ids are <prefix>-<KEY> because ids cannot contain '/'; AWS slots are <prefix>/<KEY>. Also pass cloud=gcp, region, repo_url, repo_ref, secret_names, ttl_minutes. Default secret names are AIRFLOW__API_AUTH__JWT_SECRET, FERNET_KEY, _AIRFLOW_WWW_USER_PASSWORD. The template appends AIRFLOW__SECRETS__BACKEND and BACKEND_KWARGS with every prefix null, so the identity is not asked to read connections/ or variables/ paths; bind secretAccessor only to the module's own secrets. Do not fork the template. Boot command is uv run python -m airflow_platform.stack up --projects projects/ci.yaml (up has no --target; it renders local bundles). TTL shutdown is the first runcmd so a failed boot still powers off. Pin required_version ~> 1.13.0 and the google provider in stack/versions.yaml and versions.tf; Terraform is not on PATH, so acceptance uses docker image hashicorp/terraform:1.13. Same file layout as the AWS module: mock_provider, command = plan, a second run with ttl_minutes=90 and enable_registry=true, expect_failures for a too-small machine type. envs/gcp gets no backend block and only terraform.tfvars.example. Copy .terraform.lock.hcl by running init. AWS-only details to leave behind: secret_recovery_window_days, IMDS hop limit 2, instance_initiated_shutdown_behavior.

## S8 notes (implementer)
- Module `terraform/modules/airflow-vm-gcp`, env `terraform/envs/gcp` (no backend, only `terraform.tfvars.example`), lock files from `init`. Versions: Terraform `~> 1.13.0`, `hashicorp/google ~> 7.0` (locked 7.46.2), recorded in `stack/versions.yaml`.
- Verify (provider version): WebFetch of the provider changelog was denied, so I didn't read the release that added these fields. `scheduling { provisioning_model = "STANDARD", instance_termination_action = "DELETE", max_run_duration { seconds } }` passes `terraform validate` against the GA `hashicorp/google` 7.46.2 schema, and the TTL plan run asserts 5400 s and DELETE. So 7.x supports both fields. I didn't look for the earliest version that does.
- VM: e2-medium (allowlist of >= 4 GB types, `e2-small` rejected by `expect_failures`), image family `ubuntu-os-cloud/ubuntu-2404-lts-amd64` (`ignore_changes` on it), pd-balanced 30 GB, Shielded VM (secure boot, vTPM, integrity), no public address block, OS Login on, project SSH keys blocked, cloud-init via the `user-data` metadata key. The shared template is unchanged (its `gcp` branch existed since S7).
- Secrets: `google_secret_manager_secret` `<name>-<KEY>` with auto replication and no versions; `roles/secretmanager.secretAccessor` bound per secret to the module's service account only (no project IAM). With the registry on, the SA gets `artifactregistry.reader` on that repo only.
- Firewall `<name>-allow-iap`: INGRESS, source `35.235.240.0/20` only, tcp 22 and 8080, target tag `<name>` (the instance's tag).
- Cloud NAT cost: about $0.0014/h per VM (~$0.03/day) plus $0.045/GB processed. A first boot pulls a few GB of images, so expect ~$0.10-0.20 per boot. That's above "a few cents a day" once data is counted, so `create_nat` (default true) is a variable: set it to false when the network already has a NAT in the region. Router and NAT are `<name>-router`/`<name>-nat` on `var.network`.
- TTL: the GCE scheduling deletes the VM `ttl_minutes` after it starts. The template's `shutdown -h +N` starts a little later (when cloud-init runs), so the delete normally wins; if the OS shutdown ever fires first, the VM is only stopped (no compute charge, disk remains) until someone deletes it.
- `name` is limited to 6-28 chars because it is also the service account ID (6-30).
- Not done here (S9 or a human): enabling the compute, secretmanager, iap and artifactregistry APIs, and granting the human `iap.tunnelResourceAccessor`. `tunnel_command` output: `gcloud compute start-iap-tunnel <name> 8080 --local-host-port=localhost:8080 --zone <zone> --project <project>`.
- Tests: `tests/test_terraform.py` now covers both modules (template wiring and version pins parametrized per cloud, same env shape) plus `test_gcp_module_has_no_external_ip_block` and `test_gcp_module_wiring`. pytest 74 passed. `terraform test`: GCP 4 passed (defaults, ttl_and_registry, no_nat, rejects_small_machine), AWS 3 passed.

## S8 result
*Terraform module for GCP, tested with mock providers, 14 Nov 2026 02:03.*

Implementer `claude-tc-opus`; reviewers `cursor-grok`: pass; 0 fix loop(s); branch `factory/S8`.

| check | ok | detail |
|---|---|---|
| IAP range only | yes |  |
| no external IP | yes |  |
| TTL scheduling | yes |  |
| Shielded VM | yes |  |
| registry behind enable_registry | yes |  |
| no secret versions created | yes |  |
| one shared cloud-init template | yes |  |
| no secrets in repo files | yes |  |
| terraform fmt | yes |  |
| init terraform/modules/airflow-vm-gcp | yes | If you ever set or change modules or backend configuration for Terraform, | rerun this command to reinitialize your work |
| validate terraform/modules/airflow-vm-gcp | yes | Success! The configuration is valid. |
| init terraform/envs/gcp | yes | If you ever set or change modules or backend configuration for Terraform, | rerun this command to reinitialize your work |
| validate terraform/envs/gcp | yes | Success! The configuration is valid. |
| terraform test terraform/modules/airflow-vm-gcp | yes | tests/main.tftest.hcl... pass |  | Success! 4 passed, 0 failed. |
| terraform/modules/airflow-vm-gcp has a test file | yes |  |
| terraform fmt | yes |  |
| init terraform/modules/airflow-vm-aws | yes | If you ever set or change modules or backend configuration for Terraform, | rerun this command to reinitialize your work |
| validate terraform/modules/airflow-vm-aws | yes | Success! The configuration is valid. |
| init terraform/envs/aws | yes | If you ever set or change modules or backend configuration for Terraform, | rerun this command to reinitialize your work |
| validate terraform/envs/aws | yes | Success! The configuration is valid. |
| terraform test terraform/modules/airflow-vm-aws | yes | tests/main.tftest.hcl... pass |  | Success! 3 passed, 0 failed. |
| terraform/modules/airflow-vm-aws has a test file | yes |  |
| pytest tests | yes | 74 passed in 0.65s |
| required tests present | yes | 1 found |

Review: S8 matches the prompt and spec §9. terraform test: 4 mock plans passed; pytest 74 passed. Firewall sources are only 35.235.240.0/20 on tcp 22/8080 to the instance tag; no access_config; Shielded VM on; secretAccessor per slot on this SA only; no secret version. ttl>0 sets max_run_duration and DELETE (5400s at 90). Registry count follows enable_registry (default false). One shared cloud-init, cloud=gcp, slots name-KEY. google ~> 7.0 locked 7.46.2.

For Amir: On network=default, default-allow-ssh still allows tcp/22 from 0.0.0.0/0 to every instance; this module only adds an IAP allow, so port 22 stays open and port 8080 does not. accept_s8.py fails if main.tf contains 0.0.0.0/0, so a deny rule cannot be added in this step. Plan asserts check the secretAccessor role and secret id; main.tf binds the module service account. Cloud NAT uses ALL_SUBNETWORKS in the region. The provider changelog was not fetched; validate against GA provider 7.46.2 passed.

## Additions for S9
S9 adds plan.ps1, smoke.ps1, tunnel.ps1 and remote-state.ps1, each with -Target aws|gcp and -WhatIf, and never printing secret values, plus the terraform CI job (fmt, init -backend=false, validate, tflint, terraform test; no cloud credentials). GCP output tunnel_command is: gcloud compute start-iap-tunnel <name> 8080 --local-host-port=localhost:8080 --zone <zone> --project <project>. The module does not enable compute, secretmanager, iap or artifactregistry, and does not grant the caller iap.tunnelResourceAccessor. Secret ids are <name>-<KEY>; add versions by hand after apply. create_nat defaults to true and covers every subnet in the region; set false when a NAT is already there. A positive ttl_minutes deletes the VM via max_run_duration and cloud-init also schedules shutdown -h +N first. enable_registry defaults false. name must be 6-28 lowercase characters (it is the service account id). envs/gcp has no backend; remote-state.ps1 writes backend.tf. OS Login is enabled and project-wide SSH keys are blocked. Keep terraform/templates/cloud-init.yaml.tftpl shared. Terraform is not on PATH; use docker image hashicorp/terraform:1.13. Pins: ~> 1.13.0 and hashicorp/google ~> 7.0 locked at 7.46.2. The default network's default-allow-ssh still admits tcp/22 from 0.0.0.0/0; the UI is the IAP allow on tcp/8080.

## S9 result
*Operator scripts and the terraform CI job, 14 Nov 2026 02:15.*

Implementer `claude-tc-opus`; reviewers `claude-tc-fable`: pass; 0 fix loop(s); branch `factory/S9`.

| check | ok | detail |
|---|---|---|
| smoke destroys in finally | yes |  |
| smoke checks for leftovers | yes |  |
| terraform job in CI | yes |  |
| runbook exists | yes |  |
| no secrets in repo files | yes |  |
| plan.ps1 aws -WhatIf | yes | What if: Performing the operation "Create Directory" on target "Destination: C:\Users\amir0\portfolio\airflow-platform\l |
| plan.ps1 gcp -WhatIf | yes | What if: Performing the operation "Create Directory" on target "Destination: C:\Users\amir0\portfolio\airflow-platform\l |
| smoke.ps1 aws -WhatIf | yes | What if: Performing the operation "run" on target "aws ec2 describe-instances --region eu-central-1 --filters Name=tag:N |
| smoke.ps1 gcp -WhatIf | yes | What if: Performing the operation "run" on target "gcloud compute instances list --project <project_id> --filter=name=ai |
| tunnel.ps1 aws -WhatIf | yes | tunnel.ps1: aws VM port 8080 -> http://localhost:8080 | What if: Performing the operation "run" on target "terraform out |
| remote-state.ps1 gcp -WhatIf | yes | Reminder: committing terraform/envs/gcp/backend.tf is Amir's choice. It holds only the bucket name; | without it, every  |
| zero cloud-changing calls under -WhatIf | yes |  |
| pytest tests | yes | 95 passed in 0.71s |
| required tests present | yes | 4 found |

Review: S9 delivers the four operator scripts plus shared helpers, the terraform CI job, runbook, and stack status --url. Every cloud/Terraform call is ShouldProcess-guarded; the stub recorder saw zero calls under -WhatIf. smoke.ps1 destroys in finally with the smoke vars, then checks AWS Name-tagged / GCP named instances (both set by the modules) and fails loudly. It refuses on existing state without -Force and asks y/N before apply. remote-state.ps1 creates a private, versioned, encrypted bucket. No script prints a secret value. Real (non-WhatIf) paths are untested by design.

For Amir: Before the first real smoke run: use PowerShell 7.2+ (the scripts rely on utf8NoBOM, -AsHashtable and PS7 stderr handling), set the budget alerts, and try -Target gcp on a throwaway project first. Also decide on .gitignore for terraform.tfvars / backend.tf, since two existing tests fail while those files sit on disk.

## Open questions (S9)
- tflint was not run locally (only Docker and Terraform through the stack module are allowed here). The CI job pins `setup-tflint@v4` with `tflint_version: v0.58.0` and runs it with no `.tflint.hcl`, so the default terraform ruleset applies. The first CI run is the real check, and `fmt`/`validate`/`test` passed in S7/S8 with the same files.
- The whole smoke.ps1, plan.ps1, tunnel.ps1 and remote-state.ps1 path was run only with -WhatIf. The real CLI flags (`s3api create-bucket --object-ownership`, `gcloud storage buckets update --versioning --public-access-prevention`, `ssm describe-instance-information`) come from the CLI docs as known and have not been run.
- `.gitignore` has no `*.tfvars` or `*.tfplan` rule. `test_no_tfvars_committed` and `test_no_backend_block_in_envs` check the disk, so a local `terraform.tfvars` or the `backend.tf` that remote-state.ps1 writes makes pytest fail on Amir's machine. Plan files go to `logs/`, which is ignored. Options: ignore `terraform.tfvars`, or have the tests check `git ls-files`.

