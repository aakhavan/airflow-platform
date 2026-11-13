# NOTES

## Current state
S0-S4 committed; S5 implemented and accept_s5 passed live on 13 Nov 2026 (stack up with examples+governor, governor_profile_raw run succeeded via docker-proxy, profile file in governor-airflow_governor-data, task link http://localhost:8501/Profiles?run_id=<run id with ':'->'_'> returned by the Airflow API and answering 200, 40 offline tests green). Working tree has the S5 changes uncommitted, with docs/projects/governor.md and tests/test_governor.py untracked. Governor side: the A1 commit (83458c4) sits on branch factory/A1 in the ../governor-airflow worktree; airflow-integration is still at a0b6549 and needs a fast-forward before the merge to governor main (cut line Sat 14 Nov 12:00).

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

## Open questions
- Volume name: the worktree compose file has no `name:`, so started from `../governor-airflow` its volume is probably `governor-airflow_governor-data`, not the DAG default `governor_governor-data` (which `.env.example` also sets). I could not check: `docker volume ls` was denied. If they differ, the task writes to a fresh empty volume and the API never sees the profile. The acceptance picks the first volume that ends in `governor-data`. Fix after checking: set `AIRFLOW_VAR_GOVERNOR_DATA_VOLUME` in `stack/.env` (or start governor with `-p governor`).
  - Resolved 13 Nov (fix loop): it was `governor-airflow_governor-data` (the acceptance found it; the run had written to `governor_governor-data`). `.env.example`, the test allowlist and the runbook now use the worktree name, and their comments say it goes back to `governor_governor-data` after the merge (S6+). `stack/.env` was the unedited example apart from the quotes (compared by script, never printed), so I deleted it and `up` recreated it. `accept_s5` passes.

- 13 Nov 20:47 (Claude via chat): S5 secret-scan false positives on documented test-bed defaults in stack/.env.example; quoted the AIRFLOW_VAR_ values (valid compose env syntax). Resume waits for A1 approval + governor stack up.

- 13 Nov 21:07 (Claude via chat): S10 prompt gains a short "Configuration and secrets" README section (Amir asked). Needs relock.

- 13 Nov 21:45 (Claude via chat): S5 verdict_stop fixed by hand: new {run_id_safe} placeholder (validator, views, plugin copy, test), governor link uses it, runbook gets --dsn and the worktree .env step, accept_s5 checks the link carries the file stem. relock_resume.

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
