# NOTES

## Current state
S10 is done. The README, two Mermaid diagrams in docs/architecture.md, the learning page (seven design choices and eight Q&As), an MIT LICENSE for Amir Akhavan 2026, and an optional soft-fail checkov job are in place. accept_s10 passed. Local stack and mock-provider Terraform are what has been tested; a real cloud smoke has not been run. The stranger quick start is pwsh scripts/up.ps1 -Projects projects/ci.yaml, then hello_workload at localhost:8080.

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

## S10 result (implementer)
README rewritten (what/why, quick start, add a project, targets, cost and safety, configuration and secrets, limits and future targets, repo map, CI), `docs/architecture.md` (two Mermaid flowcharts: local, cloud), `docs/learning/airflow-platform.md` (7 design choices + 8 Q&A), MIT `LICENSE`, and an optional `checkov` CI job (`bridgecrewio/checkov-action@v12`, `soft_fail: true`). accept_s10 passes; pytest 95 passed.

## Open questions (S10)
- The default `projects/projects.yaml` points governor at `../../governor-airflow/...`, and `projects.py` rejects missing paths, so a stranger's clone fails `up.ps1` without a governor checkout. The README tells them to use `-Projects projects/ci.yaml`. A cleaner fix (an examples-only default registry, or an optional flag per project) is outside S10's paths.
- No `logs/smoke-*.json` exists, so the README says "smoke-tested: not yet". The checkov job and the Mermaid diagrams were not run or rendered here; the first CI run and GitHub's renderer are the real check.

## Additions for S10
All cloud scripts dot-source scripts/_cloud.ps1; add new cloud calls only via Invoke-Cloud / Invoke-Terraform (ShouldProcess-guarded, returns $null under -WhatIf, sets $CloudExitCode, -AllowFailure, -PassThru). Terraform falls back to docker hashicorp/terraform:1.13 when not on PATH. stack status --url returns remote=True, mem_mb=0 and uses the unauthenticated /api/v2/monitor/health; trigger/wait --url authenticate with local stack/.env credentials (defaults airflow/airflow). Open items carried over: .gitignore lacks terraform.tfvars, backend.tf and *.tfplan rules, and test_no_tfvars_committed / test_no_backend_block_in_envs check the disk, so a local tfvars or the backend.tf that remote-state.ps1 writes breaks pytest locally (option: ignore those files or switch tests to git ls-files). tflint and the terraform CI job have not run yet; the first CI run on this branch is the real check. Scripts require PowerShell 7.2+ (utf8NoBOM, ConvertFrom-Json -AsHashtable, native stderr semantics). The acceptance stub trick (logs/stub_bin on PATH recording calls) is reusable for any future -WhatIf check.

## S10 result
*README, architecture diagram and the learning page, 14 Nov 2026 02:44.*

Implementer `claude-tc-opus`; reviewers `cursor-grok`: pass, `claude-tc-fable`: pass; 0 fix loop(s); branch `factory/S10`.

| check | ok | detail |
|---|---|---|
| README section: quick start | yes |  |
| README section: add a project | yes |  |
| README section: targets | yes |  |
| README section: cost | yes |  |
| README section: limits | yes |  |
| README section: repo map | yes |  |
| README has no TODO | yes |  |
| Kubernetes named as future target | yes |  |
| two mermaid diagrams | yes | 2 |
| mermaid blocks start with a diagram type | yes |  |
| learning page exists | yes |  |
| LICENSE is MIT | yes |  |
| relative links resolve | yes |  |
| no secrets in repo files | yes |  |

Review: cursor-grok: pass | claude-tc-fable: pass

For Amir: The first quick-start snippet is pwsh scripts/up.ps1, which fails without a sibling governor checkout; the next paragraph gives -Projects projects/ci.yaml. The diagram subtitle on the local subgraph says image airflow-platform:local, which is the Airflow image; postgres and docker-proxy use their own images. Interview answer 7 says the TTL deletes the VM even if everything else fails; on AWS that still depends on cloud-init scheduling shutdown. The README states shutdown, then terminate.

## Additions for the next plan
S10 is the last factory step (HUMAN release). A clone without governor-airflow beside it should start with pwsh scripts/up.ps1 -Projects projects/ci.yaml; projects/projects.yaml points at ../../governor-airflow and projects.py rejects a missing path. No logs/smoke-*.json exists, so the README says real cloud smoke has not been run. checkov and the Mermaid diagrams have not executed; the first CI run and GitHub's renderer are the check. Carry-over: .gitignore has no terraform.tfvars, backend.tf, or *.tfplan rule, so a local copy fails test_no_tfvars_committed and test_no_backend_block_in_envs. Scripts need PowerShell 7.2+.
