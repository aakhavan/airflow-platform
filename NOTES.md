# NOTES

## Current state
S8 adds terraform/modules/airflow-vm-gcp and terraform/envs/gcp (no backend block, only terraform.tfvars.example). The VM is e2-medium, Ubuntu 24.04, pd-balanced 30 GB, Shielded VM, with no external IP. Ingress from this module is tcp 22 and 8080 from 35.235.240.0/20 to the instance tag. Egress uses Cloud NAT when create_nat is true (the default). The service account has roles/secretmanager.secretAccessor on empty slots named <name>-<KEY> (default prefix airflow-platform) and, only if enable_registry is true, roles/artifactregistry.reader on that repository. ttl_minutes 0 leaves the scheduling block off; a positive value sets max_run_duration to ttl*60 seconds, provisioning_model STANDARD and instance_termination_action DELETE. The shared cloud-init template is rendered with cloud=gcp and runs shutdown -h +N only when the TTL is positive. Pins are Terraform ~> 1.13.0 and hashicorp/google ~> 7.0, locked at 7.46.2. Acceptance passed: GCP mock plans 4 passed, AWS 3 passed, pytest 74 passed, using hashicorp/terraform:1.13 because Terraform is not on PATH.

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
