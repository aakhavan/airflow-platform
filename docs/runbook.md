# Runbook: cloud VM, smoke test and cleanup

Everything here costs real money and touches your own cloud accounts, so a human runs it, not an agent. The scripts
(`scripts/plan.ps1`, `smoke.ps1`, `tunnel.ps1`, `remote-state.ps1`) are PowerShell 7. Each takes `-Target aws|gcp`
and `-WhatIf`. With `-WhatIf` a script prints every command it would run and runs none of them, so it needs no login.

Terraform is pinned to `~> 1.13.0`. If `terraform` is not on PATH, the scripts run `hashicorp/terraform:1.13` in
Docker. They mount the repo, `~/.aws` (AWS) or `%APPDATA%\gcloud` (GCP) into the container and pass `AWS_PROFILE`
/ `AWS_REGION` if you set them.

## One-time setup (Amir)

1. **Budget alert, one per account, before anything else.** Set it to €5 a month with an email at 50% and 100%.
   - AWS: Billing → Budgets → Create budget → "Monthly cost budget", €5 (or $5), your email.
   - GCP: Billing → Budgets & alerts → Create budget, scoped to the project, €5, thresholds 50% and 100%.
2. **CLI logins.**
   - AWS: install the AWS CLI v2 and the **Session Manager plugin** (`tunnel.ps1` needs it). Run `aws configure sso`
     (or `aws configure`), then `aws sts get-caller-identity`. Set `AWS_PROFILE` if you use a named profile.
   - GCP: install the gcloud CLI. Run `gcloud auth login`, then `gcloud auth application-default login` (Terraform
     uses ADC), then `gcloud config set project <id>`. Enable the APIs, which the module does not do:
     `gcloud services enable compute.googleapis.com secretmanager.googleapis.com iap.googleapis.com`
     (add `artifactregistry.googleapis.com` if `enable_registry = true`). Give yourself
     `roles/iap.tunnelResourceAccessor` on the project, which the module does not grant either.
3. **Variables.** Copy `terraform/envs/<target>/terraform.tfvars.example` to `terraform.tfvars` and fill in at
   least `repo_url`, plus `project_id` on GCP. Never commit it. `.gitignore` has no `*.tfvars` rule yet, and the
   offline test `test_no_tfvars_committed` fails while the file is on disk, so keep it out of CI checkouts. On GCP, set
   `create_nat = false` if the network already has a Cloud NAT.
4. **Optional remote state.** `./scripts/remote-state.ps1 -Target aws -Bucket <globally-unique-name>` creates a
   private, versioned, encrypted bucket, writes `terraform/envs/<target>/backend.tf` and migrates the local state.
   Whether to commit `backend.tf` is your call. While it sits in the working tree, the offline test
   `test_no_backend_block_in_envs` fails.

## Deploy and fill the secrets (after the first apply)

1. `./scripts/plan.ps1 -Target gcp`. It checks the login (printing only the account id or email), runs
   `terraform init` and `plan -out`, and writes `logs/plan-<target>-<ts>.txt` (resource headers and the `Plan:` line).
   Then apply that plan with your own `terraform apply logs/plan-<target>-<ts>.tfplan`, run from
   `terraform/envs/<target>`.
2. Terraform creates **empty** secret slots. `terraform output secret_names` lists them: `<name>/<KEY>` on AWS,
   `<name>-<KEY>` on GCP. Add each value by hand and never paste it into a file in this repo:
   - AWS: `aws secretsmanager put-secret-value --secret-id <name>/FERNET_KEY --secret-string file://fernet.txt`
   - GCP: `gcloud secrets versions add <name>-FERNET_KEY --data-file=fernet.txt`
   Make the values locally (Fernet key: `uv run python -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())" > fernet.txt`),
   then delete the files. The VM reads the slots **at boot**. If you fill them after the VM is up, reboot it (or
   apply again with a new VM) so `stack/.env` is rendered again. A slot with no value keeps the stack's local default.
3. `./scripts/tunnel.ps1 -Target gcp` forwards the UI to http://localhost:8080 until Ctrl+C. Use `-LocalPort 18080`
   if the local stack already uses 8080.

## Smoke test

```powershell
./scripts/smoke.ps1 -Target gcp -WhatIf   # free: shows every step
./scripts/smoke.ps1 -Target gcp           # real: about $0.10 and 10-20 minutes
```

It uses the name `airflow-platform-smoke` and `ttl_minutes=90`, so the VM deletes itself after 90 minutes even if
everything else fails. On AWS the secret slots are deleted right away on destroy. The steps:

1. Refuses if `terraform/envs/<target>` already has resources in state. `-Force` overrides this, but the cleanup
   then **destroys those resources too**, so don't use it against a real deployment. Use another clone or wait.
2. Plans, prints the resources and an approximate cost (a price table in the script; check the plan), and asks for `y`.
   `-Yes` skips the question.
3. Applies, waits for SSM `Online` (AWS) or `RUNNING` (GCP/IAP), and opens `tunnel.ps1` as a background job on
   `localhost:18080`.
4. Runs `stack status --url http://localhost:18080` until the stack is healthy (15 min), then triggers
   `hello_workload` and waits for success (10 min). The REST calls log in with the user and password in your local
   `stack/.env` (default `airflow`/`airflow`). The smoke VM's slots are empty, so it uses the same defaults.
5. **finally:** `terraform destroy -auto-approve`, then a search for instances named `airflow-platform-smoke`.
   If any remain, the script fails loudly with their ids. `-KeepOnFailure` skips the destroy, but only when a step
   failed, so you can debug. Destroy by hand afterwards (below).

### Reading the log

`logs/smoke-<target>-<ts>.json` holds `ok` plus one entry per phase (`preflight`, `plan`, `apply`,
`wait-for-access`, `tunnel`, `health`, `hello_workload`, `destroy`, `leftovers`), each with `status`
(`ok`, `failed`, `skipped`, `declined`) and `seconds`. `detail` holds the error of a failed phase. A run passed
only if `ok` is true **and** `leftovers` is `ok`.

## Cleaning up by hand (the script died, or -KeepOnFailure)

1. From `terraform/envs/<target>`:
   `terraform destroy -var ttl_minutes=90 -var name=airflow-platform-smoke` (on AWS add
   `-var secret_recovery_window_days=0`). With no `terraform` on PATH, run the same command in
   `hashicorp/terraform:1.13`, mounted the way `scripts/_cloud.ps1` mounts it.
2. Check that nothing is left:
   - AWS: `aws ec2 describe-instances --filters Name=tag:Name,Values=airflow-platform-smoke Name=instance-state-name,Values=pending,running,stopping,stopped --query "Reservations[].Instances[].InstanceId" --output text`,
     then `aws secretsmanager list-secrets --filters Key=name,Values=airflow-platform-smoke`.
   - GCP: `gcloud compute instances list --filter="name=airflow-platform-smoke"`,
     `gcloud secrets list --filter="name~airflow-platform-smoke"`, `gcloud compute routers list`.
3. If the state is lost but resources remain, delete them in the console. Everything the module creates carries
   the name `airflow-platform-smoke`: instance, security group or firewall, IAM role or service account, secrets,
   and router/NAT on GCP.
4. Stop any tunnel that is still running: `Get-Job smoke-tunnel-* | Remove-Job -Force`.
