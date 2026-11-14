"""Offline checks of the S9 operator scripts, the terraform CI job and `stack status --url` (docs/spec.md §10, §11).
Structural only: nothing here runs pwsh, terraform or a cloud CLI."""
import re
from pathlib import Path

import pytest
import yaml

from airflow_platform import stack

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
CLOUD_SCRIPTS = ("plan.ps1", "smoke.ps1", "tunnel.ps1", "remote-state.ps1")
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
SECRETISH = re.compile(r"secret|password|token", re.I)


def _read(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8")


def _code(text: str) -> str:
    """Script text without comment lines and trailing comments (good enough for these scripts: no '#' in strings
    is relied on by the checks below)."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


@pytest.mark.parametrize("name", CLOUD_SCRIPTS)
def test_scripts_support_whatif(name):
    text = _read(name)
    assert "[CmdletBinding(SupportsShouldProcess)]" in text
    assert "Set-StrictMode -Version Latest" in text
    assert "$ErrorActionPreference = 'Stop'" in text
    assert re.search(r"\[ValidateSet\('aws', 'gcp'\)\]\[string\]\$Target", text)
    assert ". (Join-Path $PSScriptRoot '_cloud.ps1')" in text
    # Cloud and Terraform calls go through the ShouldProcess-guarded helpers, never straight to the CLI.
    code = _code(text)
    assert not re.search(r"^\s*&?\s*(aws|gcloud|terraform)\s+[^{=\s]", code, re.M), name  # not `terraform {` / `aws = @{`
    assert not re.search(r"&\s*['\"]?(aws|gcloud|terraform)['\"]?\s", code), name


def test_cloud_helper_guards_every_call():
    text = _read("_cloud.ps1")
    invoke = text.split("function Invoke-Cloud", 1)[1].split("\nfunction ", 1)[0]
    assert "[CmdletBinding(SupportsShouldProcess)]" in invoke
    # ShouldProcess is checked before the external command runs.
    assert invoke.index("$PSCmdlet.ShouldProcess") < invoke.index("& $Exe @Arguments")
    assert "hashicorp/terraform:1.13" in text  # the docker fallback when terraform is not on PATH


def test_smoke_destroys_in_finally():
    text = _read("smoke.ps1")
    code = _code(text)
    main_try = code.split("\ntry {", 1)
    assert len(main_try) == 2, "smoke.ps1 has a top-level try"
    body, final = main_try[1].split("\n} finally {", 1)
    assert "'apply'" in body and "'-auto-approve'" in final
    destroy = final.index("'destroy'")
    leftovers = final.index("'leftovers'")
    assert destroy < leftovers, "destroy first, then the leftover check"
    assert "$SmokeName" in final[leftovers:] and "throw" in final[leftovers:]
    assert "$SmokeName = 'airflow-platform-smoke'" in code
    assert '"ttl_minutes=$TtlMinutes"' in code and "$TtlMinutes = 90" in code
    assert '"name=$SmokeName"' in code
    # Only -KeepOnFailure (and only after a failure) skips the destroy.
    assert "$keep = $KeepOnFailure -and $failed" in final
    # The JSON log is written in the finally block too.
    assert "smoke-$Target-$stamp.json" in code and "ConvertTo-Json" in final
    # The y/N question comes before the apply, and -Yes skips it.
    assert code.index("Read-Host") < code.index("Invoke-Phase 'apply'") and "-not $Yes" in code
    assert "approximate, check the plan" in code.lower()


def test_smoke_refuses_existing_state_unless_force():
    code = _code(_read("smoke.ps1"))
    assert "'state', 'list'" in code and "if (-not $Force)" in code


def test_no_script_echoes_secret_values():
    offenders = []
    for path in SCRIPTS.glob("*.ps1"):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not re.search(r"\b(Write-Host|Write-Output|Write-Information|Write-Verbose)\b", line):
                continue
            names = re.findall(r"\$(?:\{)?(?:script:|env:)?([A-Za-z_][\w]*)", line)
            bad = [v for v in names if SECRETISH.search(v)]
            if bad:
                offenders.append(f"{path.name}:{n}: {bad}")
    assert not offenders, offenders


def test_plan_prints_only_identity_ids():
    text = _read("_cloud.ps1")
    assert "'sts', 'get-caller-identity', '--query', 'Account'" in text
    assert "'--format=value(account)'" in text


def test_remote_state_bucket_settings():
    text = _read("remote-state.ps1")
    assert "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true" in text
    assert "Status=Enabled" in text and "SSEAlgorithm" in text
    assert "--uniform-bucket-level-access" in text and "--public-access-prevention" in text and "--versioning" in text
    assert 'backend "s3"' in text and 'backend "gcs"' in text and "-migrate-state" in text
    assert "Amir's choice" in text


def test_tunnel_reads_terraform_outputs():
    text = _read("tunnel.ps1") + _read("_cloud.ps1")
    assert "Get-TfOutputs" in text and "tunnel_command" in text
    assert "localPortNumber=" in text and "--local-host-port=localhost:" in text


def test_ci_has_terraform_job():
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = wf["jobs"]["terraform"]
    assert job["runs-on"] == "ubuntu-latest"
    uses = [s.get("uses", "") for s in job["steps"]]
    assert any(u.startswith("hashicorp/setup-terraform@v") for u in uses)
    assert any(u.startswith("terraform-linters/setup-tflint@v") for u in uses)
    setup = next(s for s in job["steps"] if s.get("uses", "").startswith("hashicorp/setup-terraform@"))
    assert setup["with"]["terraform_version"] == "~1.13.0"
    runs = "\n".join(s.get("run", "") for s in job["steps"])
    assert "terraform fmt -check -recursive" in runs
    assert "init -backend=false" in runs and "validate" in runs
    assert "envs/aws" in runs and "envs/gcp" in runs
    assert "tflint --recursive" in runs
    assert "terraform -chdir=\"$mod\" test" in runs
    assert "modules/airflow-vm-aws" in runs and "modules/airflow-vm-gcp" in runs
    text = yaml.safe_dump(job)
    assert "secrets." not in text and "credentials" not in text.lower()
    assert " apply" not in runs and " plan" not in runs


# --- stack status --url (through a tunnel) ---------------------------------------------------

HEALTHY = {"metadatabase": {"status": "healthy"},
           "scheduler": {"status": "healthy", "latest_scheduler_heartbeat": "2026-11-14T00:00:00Z"},
           "triggerer": {"status": "healthy"}, "dag_processor": {"status": "healthy"}}


def test_remote_status_line_up():
    line = stack.remote_status_line(HEALTHY, "3.3.2", "http://localhost:18080")
    assert line["up"] is True and line["remote"] is True
    assert line["services"]["scheduler"] == "healthy" and line["url"] == "http://localhost:18080"


@pytest.mark.parametrize("health", [
    {**HEALTHY, "scheduler": {"status": "unhealthy"}},
    {"metadatabase": {"status": "healthy"}},
    {**HEALTHY, "triggerer": {"status": None}},
    {},
])
def test_remote_status_line_down(health):
    assert stack.remote_status_line(health, "", "u")["up"] is False


def test_status_url_skips_docker(monkeypatch, capsys):
    seen = {}
    monkeypatch.setattr(stack, "remote_status", lambda url, dags: seen.update(url=url, dags=dags) or {"up": True})
    monkeypatch.setattr(stack, "_run", lambda *a, **k: pytest.fail("status --url must not call docker"))
    assert stack.main(["status", "--url", "http://localhost:18080"]) == 0
    assert seen == {"url": "http://localhost:18080", "dags": False}


@pytest.mark.parametrize("argv", [["status"], ["trigger", "d"], ["wait", "d", "r"]])
def test_url_option_on_status_trigger_wait(argv, monkeypatch, capsys):
    seen = {}

    def fake(args):
        seen["url"] = args.url
        return {"ok": True, "up": True, "state": "success", "run_id": "r"}

    monkeypatch.setattr(stack, f"cmd_{argv[0]}", fake)
    assert stack.main(argv + ["--url", "http://localhost:18080"]) == 0
    assert seen["url"] == "http://localhost:18080"
