# NOTES

## Current state
S4 is in place and accept_s4 passed live on 13 Nov 2026 (plugin loaded with 2 external views and 1 global operator link, hello_workload link resolved through the extra-links REST route, 36 tests passing). The stack is left up on the real registry, where examples temporarily carries a view and task_link aimed at http://localhost:8080/docs. The plugin is stdlib+yaml+airflow only, copies the views logic from src/airflow_platform/views.py under an AST-equality test, mounts plugins/ read-only, and degrades to registering nothing on a broken registry. The per-DAG dag-tab limitation and the 3.3 external_views keys, get_link signature, and plugins/extra-links routes are recorded in NOTES.md from the running server's OpenAPI schema since the docs fetch was denied. Changes are uncommitted; plugins/ and the new views module and test are untracked.

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
- S4 verify (plugins): WebFetch of the 3.3 "Plugins" / "Custom view plugin" docs was denied again, so these facts come from the **running 3.3.2 server's `/openapi.json`** and the live plugin. Plugins route: `GET /api/v2/plugins` (`limit`, `offset`; also `/api/v2/plugins/importErrors`). `external_views` keys (`ExternalViewResponse`): `name` and `href` (required), `icon`, `icon_dark_mode`, `url_route`, `category`, `nav_top_level` (default false), and `destination`, which is one of `nav|dag|dag_run|task|task_instance|base` (default `nav`). The schema has **no key that limits a `dag` tab to some DAGs** (by id prefix or tag), so the tab shows on every DAG, as spec §7 allows. Extra-links route: `GET /api/v2/dags/{dag_id}/dagRuns/{run_id}/taskInstances/{task_id}/links` (`map_index`, `try_number`) returns `{"extra_links": {name: url}}`, so `stack links` uses `"source": "api"` and the computed fallback isn't needed. `get_link(self, operator, *, ti_key)` with `BaseOperatorLink` from `airflow.sdk` works live: the run's link came back from the API. The signature wasn't checked against the docs text. Airflow loads `plugins/project_views/__init__.py` as module `__init__` (source `$PLUGINS_FOLDER/project_views/__init__.py`), so relative imports would break, and the views logic is copied in. `AIRFLOW__CORE__LAZY_LOAD_PLUGINS` is not set: the views and the link work with the default, and the docs couldn't be read to show it's needed.

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
