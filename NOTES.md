# NOTES

## Current state
S7 adds the AWS Terraform module terraform/modules/airflow-vm-aws, the env root terraform/envs/aws (no backend, only terraform.tfvars.example), and the shared cloud-init template. A t3.medium Ubuntu 24.04 VM (AMI from the Canonical SSM parameter, gp3 30 GB encrypted) has no ingress, IMDSv2 required, an SSM instance profile, and empty Secrets Manager slots for AIRFLOW__API_AUTH__JWT_SECRET, FERNET_KEY and _AIRFLOW_WWW_USER_PASSWORD. The role may call GetSecretValue only on those ARNs. ECR exists only when enable_registry is true. ttl_minutes 0 stops on shutdown; a positive TTL terminates and cloud-init runs shutdown -h +N. Versions are Terraform ~> 1.13.0 and hashicorp/aws ~> 6.0 (locked 6.73.0). Acceptance passed with mock-provider plan tests (3 passed) and pytest (68 passed). Terraform is not on PATH; checks used hashicorp/terraform:1.13.

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
