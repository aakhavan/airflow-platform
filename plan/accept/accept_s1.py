"""S1 acceptance: image, lean stack up, status line."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import check, docker, finish, guarded, no_secrets, pytest_check, read, stack, tail  # noqa: E402


def static():
    c = read("stack/compose.yaml")
    first = c.splitlines()[0] if c else ""
    check("compose names its official source", "airflow.apache.org" in first and "3.3." in first, first[:120])
    for bad in ("redis", "airflow-worker", "flower", "CeleryExecutor"):
        check(f"compose has no {bad}", bad not in c)
    check("LocalExecutor", "LocalExecutor" in c)
    d = read("image/Dockerfile")
    check("Dockerfile uses apache/airflow 3.3 python3.12", "apache/airflow:" in d and "python3.12" in d and "3.3." in d)
    check("providers installed with constraints", "constraints-" in d and "--constraint" in d)
    req = read("image/requirements.txt").lower()
    check("requirements are providers only", bool(req) and all(l.strip().startswith("apache-airflow-providers-") or not l.strip() or l.strip().startswith("#") for l in req.splitlines()))
    check("versions.yaml records the version", "3.3." in read("stack/versions.yaml"))
    no_secrets()


def live():
    s, r = stack("status", timeout=120)
    if not check("status prints JSON", bool(s), tail(r)):
        return
    check("stack up", s.get("up") is True, str(s.get("services"))[:200])
    check("airflow 3.3.x", str(s.get("airflow_version", "")).startswith("3.3."), str(s.get("airflow_version")))
    svcs = s.get("services") or {}
    check("five airflow services + postgres", len(svcs) >= 6, ",".join(svcs))
    check("all services healthy", svcs and all(str(v).lower() in ("healthy", "running(healthy)", "ok") for v in svcs.values()), str(svcs)[:200])
    mem = int(s.get("mem_mb") or 0)
    check("stack under 3 GB RAM", 0 < mem < 3072, f"{mem} MB")
    img = docker("image", "inspect", "airflow-platform:local", "--format", "{{.Size}}")
    check("image built", img.returncode == 0, tail(img))


guarded(static)
guarded(live)
guarded(pytest_check, "tests", ["test_compose_has_no_celery_services", "test_every_service_has_healthcheck", "test_executor_is_local",
                                "test_dockerfile_installs_with_constraints", "test_status_line_shape"])
finish("S1")
