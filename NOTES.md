# NOTES

## Current state
S9 is complete and accepted: scripts/plan.ps1, smoke.ps1, tunnel.ps1, remote-state.ps1 and the shared scripts/_cloud.ps1 exist, all with -Target aws|gcp and -WhatIf, every cloud/Terraform/docker/uv call routed through a ShouldProcess-guarded Invoke-Cloud. smoke.ps1 refuses on existing state without -Force, plans and prints an approximate cost, asks y/N, applies ttl_minutes=90 name=airflow-platform-smoke, waits for SSM/IAP, tunnels on localhost:18080, checks health and runs hello_workload, and in finally destroys and checks for leftover instances, writing logs/smoke-<target>-<ts>.json. remote-state.ps1 creates a private, versioned, encrypted S3/GCS bucket and writes backend.tf. CI has a credential-free terraform job (fmt, validate, tflint, terraform test). docs/runbook.md covers Amir's one-time steps, smoke and manual cleanup. pytest: 95 passed. Nothing has run against a real cloud; uncommitted on branch factory/S9.

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

## Additions for S10
All cloud scripts dot-source scripts/_cloud.ps1; add new cloud calls only via Invoke-Cloud / Invoke-Terraform (ShouldProcess-guarded, returns $null under -WhatIf, sets $CloudExitCode, -AllowFailure, -PassThru). Terraform falls back to docker hashicorp/terraform:1.13 when not on PATH. stack status --url returns remote=True, mem_mb=0 and uses the unauthenticated /api/v2/monitor/health; trigger/wait --url authenticate with local stack/.env credentials (defaults airflow/airflow). Open items carried over: .gitignore lacks terraform.tfvars, backend.tf and *.tfplan rules, and test_no_tfvars_committed / test_no_backend_block_in_envs check the disk, so a local tfvars or the backend.tf that remote-state.ps1 writes breaks pytest locally (option: ignore those files or switch tests to git ls-files). tflint and the terraform CI job have not run yet; the first CI run on this branch is the real check. Scripts require PowerShell 7.2+ (utf8NoBOM, ConvertFrom-Json -AsHashtable, native stderr semantics). The acceptance stub trick (logs/stub_bin on PATH recording calls) is reusable for any future -WhatIf check.
