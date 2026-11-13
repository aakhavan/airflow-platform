"""Terraform helpers for S7-S9 acceptance: local terraform, else the pinned Docker image. Never touches a cloud."""
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT, check, run, tail  # noqa: E402

TF_IMAGE = os.environ.get("PLATFORM_TF_IMAGE", "hashicorp/terraform:1.13")
NO_CREDS = {k: "" for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE",
                            "GOOGLE_APPLICATION_CREDENTIALS", "CLOUDSDK_CONFIG")}


def tf(args: list[str], rel: str, timeout: float = 900):
    env = {**os.environ, **NO_CREDS, "TF_IN_AUTOMATION": "1", "AWS_EC2_METADATA_DISABLED": "true"}
    if shutil.which("terraform"):
        return run(["terraform", *args], cwd=ROOT / rel, timeout=timeout, env=env)
    return run(["docker", "run", "--rm", "-v", f"{ROOT.as_posix()}:/w", "-w", f"/w/{rel}", TF_IMAGE, *args],
               timeout=timeout, env=env)


def module_checks(mod: str, env_dir: str) -> None:
    r = tf(["fmt", "-check", "-recursive"], "terraform")
    check("terraform fmt", r.returncode == 0, tail(r))
    for rel in (mod, env_dir):
        r = tf(["init", "-backend=false", "-input=false"], rel)
        if check(f"init {rel}", r.returncode == 0, tail(r)):
            r = tf(["validate", "-no-color"], rel)
            check(f"validate {rel}", r.returncode == 0, tail(r))
    r = tf(["test", "-no-color"], mod, timeout=1200)
    check(f"terraform test {mod}", r.returncode == 0 and "fail" not in r.stdout.lower().split("success")[-1], tail(r))
    check(f"{mod} has a test file", any((ROOT / mod / "tests").glob("*.tftest.hcl")))
