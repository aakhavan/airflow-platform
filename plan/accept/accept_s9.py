"""S9 acceptance: every cloud script works with -WhatIf and makes zero cloud calls; terraform CI job exists."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT, check, finish, guarded, no_secrets, pwsh, pytest_check, read, tail  # noqa: E402

STUB = ROOT / "logs" / "stub_bin"
CALLS = ROOT / "logs" / "stub_calls.txt"


def make_stubs() -> dict:
    STUB.mkdir(parents=True, exist_ok=True)
    CALLS.write_text("", encoding="utf-8")
    for name in ("aws", "gcloud", "terraform"):
        (STUB / f"{name}.cmd").write_text(f"@echo {name} %*>>\"{CALLS}\"\r\n@exit /b 0\r\n", encoding="utf-8")
        sh = STUB / name
        sh.write_text(f"#!/bin/sh\necho \"{name} $*\" >> \"{CALLS.as_posix()}\"\nexit 0\n", encoding="utf-8")
        os.chmod(sh, 0o755)
    env = dict(os.environ)
    env["PATH"] = str(STUB) + os.pathsep + env.get("PATH", "")
    return env


def whatif():
    env = make_stubs()
    for script, args in [("scripts/plan.ps1", ["-Target", "aws"]), ("scripts/plan.ps1", ["-Target", "gcp"]),
                         ("scripts/smoke.ps1", ["-Target", "aws", "-Yes"]), ("scripts/smoke.ps1", ["-Target", "gcp", "-Yes"]),
                         ("scripts/tunnel.ps1", ["-Target", "aws"]), ("scripts/remote-state.ps1", ["-Target", "gcp", "-Bucket", "x"])]:
        r = pwsh(script, *args, "-WhatIf", env=env, timeout=300)
        check(f"{Path(script).name} {args[1]} -WhatIf", r.returncode == 0, tail(r))
    calls = [l for l in CALLS.read_text(encoding="utf-8").splitlines() if l.strip()]
    mutating = [l for l in calls if any(w in l for w in (" apply", " destroy", " create", "start-session", "start-iap-tunnel",
                                                         " mb ", "s3api create", " plan"))]
    check("zero cloud-changing calls under -WhatIf", not mutating, "; ".join(mutating[:3]))


def static():
    smoke = read("scripts/smoke.ps1")
    check("smoke destroys in finally", "finally" in smoke and "destroy" in smoke.split("finally", 1)[-1])
    check("smoke checks for leftovers", "airflow-platform-smoke" in smoke)
    check("terraform job in CI", "terraform" in read(".github/workflows/ci.yml") and "tflint" in read(".github/workflows/ci.yml"))
    check("runbook exists", (ROOT / "docs/runbook.md").is_file())
    no_secrets()


guarded(static)
guarded(whatif)
guarded(pytest_check, "tests", ["test_scripts_support_whatif", "test_smoke_destroys_in_finally", "test_no_script_echoes_secret_values",
                                "test_ci_has_terraform_job"])
finish("S9")
