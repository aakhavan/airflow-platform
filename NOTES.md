# NOTES

## Current state
S0 through S5 are done, including the governor end-to-end run. S6 adds CI for the offline tests and the local stack: .github/workflows/ci.yml, the examples-only projects/ci.yaml, and scripts/ci-local.ps1. The python job runs uv sync --frozen and pytest. The stack job starts that registry, requires zero DAG import errors, runs hello_workload to success, uploads compose logs on failure, and always removes volumes. ci-local.ps1 repeats that sequence as compose project airflow_platform_ci on port 8081, so the dev project's generated files in stack/ stay untouched. stack.py takes --compose-project and --port on every subcommand, and wait exits non-zero unless the run state is success. Local acceptance passed (hello_workload success, CI volumes removed, 62 tests). GitHub has not run the workflow yet.

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

## Additions for S7
S7 is the AWS Terraform module and mock-provider tests. Leave .github/workflows/ci.yml without a terraform job and without secrets; the terraform job arrives in S9, and permissions stay contents: read. Pytest on a runner has no ../governor-airflow checkout: test_projects.py expects the repo registry to fail only on governor's missing dags.local, and test_governor.py skips only the Streamlit page-name check. The stack job renders projects/ci.yaml (examples only). Every python -m airflow_platform.stack subcommand takes --compose-project (default airflow_platform) and --port (AIRFLOW_PORT from stack/.env, else 8080). Any other compose project writes its generated env and override under logs/<project>/, not into stack/. The workflow has not executed on GitHub; scripts/ci-local.ps1 is the run that passed.
