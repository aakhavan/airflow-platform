"""S5 acceptance: governor runs as a project end to end (manual profile DAG, report reachable)."""
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (ROOT, check, docker, finish, guarded, http_status, no_secrets, pytest_check, read,  # noqa: E402
                     stack, tail, trigger_and_wait)

WT = ROOT.parent / "governor-airflow"


def preconditions() -> bool:
    ok = check("governor worktree exists", (WT / "airflow/dags/governor_profile_raw.py").is_file(), str(WT))
    img = docker("image", "inspect", "governor:local", "--format", "{{.Id}}")
    ok &= check("governor:local image exists", img.returncode == 0, tail(img))
    pg = docker("ps", "--filter", "publish=55432", "--format", "{{.Names}}")
    ok &= check("governor test bed up on 55432", bool(pg.stdout.strip()), pg.stdout.strip() or "not running")
    ok &= check("governor api healthy", http_status("http://localhost:8000/health") == 200)
    ok &= check("governor ui up", http_status("http://localhost:8501/_stcore/health") == 200)
    return ok


def static():
    reg = read("projects/projects.yaml")
    check("governor in registry", "name: governor" in reg)
    check("governor view + link", "localhost:8501" in reg and "dag_prefix" in reg)
    check("runbook exists", (ROOT / "docs/projects/governor.md").is_file())
    no_secrets()


def live():
    _, r = stack("up", timeout=900)
    check("stack up with governor", r.returncode == 0, tail(r))
    res = trigger_and_wait("governor_profile_raw", timeout=600)
    if res.get("state") != "success":
        return
    vol = docker("volume", "ls", "--format", "{{.Name}}")
    gvol = next((v for v in vol.stdout.split() if v.endswith("governor-data")), "")
    fname = res["run_id"].replace(":", "_") + ".json"
    ls = docker("run", "--rm", "-v", f"{gvol}:/data:ro", "alpine:3.20", "ls", "/data/profiles")
    check("profile file written to governor volume", fname in ls.stdout, (gvol + " " + ls.stdout[-120:]))
    l, r = stack("links", "governor_profile_raw", res["run_id"], "profile", timeout=120)
    url = next((v for v in ((l or {}).get("links") or {}).values() if "8501" in str(v)), "")
    check("task link points at the governor UI", bool(url), str(l or tail(r))[:200])
    stem = fname[:-5]
    check("task link carries the profile's file-safe run id", bool(url) and stem in urllib.parse.unquote(url), url[:200])
    if url:
        check("report link answers 200", http_status(url) == 200, url)


if guarded(preconditions):
    guarded(static)
    guarded(live)
else:
    guarded(static)
guarded(pytest_check, "tests", ["test_registry_has_governor_with_view_and_link", "test_governor_link_targets_profiles_page",
                                "test_env_example_has_no_values_beyond_documented_defaults",
                                "test_link_for_run_id_safe"])
finish("S5")
