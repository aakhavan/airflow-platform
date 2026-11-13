"""S2 acceptance: socket proxy, hello workload runs as a container, Airflow image stays thin."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (DENYLIST, ROOT, check, dag_imports_ok, docker, finish, guarded, no_secrets,  # noqa: E402
                     pytest_check, read, stack, tail, trigger_and_wait)


def static():
    c = read("stack/compose.yaml")
    check("docker-proxy service", "docker-socket-proxy" in c)
    # the socket may appear exactly once (the proxy's volume)
    check("raw socket mounted only once", c.count("/var/run/docker.sock") == 1, f"{c.count('/var/run/docker.sock')} mounts")
    ok, bad = dag_imports_ok(ROOT / "dags")
    check("DAGs import only airflow/providers/stdlib", ok, bad)
    check("hello workload exists", (ROOT / "workloads/hello/Dockerfile").is_file())
    no_secrets()


def thin_image():
    r = docker("run", "--rm", "--entrypoint", "python", "airflow-platform:local", "-m", "pip", "list", "--format=freeze")
    if not check("pip list in airflow image", r.returncode == 0, tail(r)):
        return
    names = {l.split("==")[0].lower() for l in r.stdout.splitlines()}
    leaked = [d for d in DENYLIST if d in names]
    check("no project libraries in airflow image", not leaked, ",".join(leaked))


def live():
    s, r = stack("status", timeout=120)
    check("no DAG import errors", bool(s) and s.get("import_errors") == 0, str((s or {}).get("import_errors", tail(r))))
    res = trigger_and_wait("hello_workload")
    if res.get("state") == "success":
        lg, r = stack("logs", "hello_workload", res["run_id"], "hello", timeout=120)
        text = r.stdout
        check("workload JSON line in task log", '"workload": "hello"' in text or '"workload":"hello"' in text, text[-200:])


guarded(static)
guarded(thin_image)
guarded(live)
guarded(pytest_check, "tests", ["test_hello_dag_imports_only_allowed_modules", "test_no_airflow_service_mounts_docker_socket",
                                "test_trigger_payload_shape", "test_wait_parses_states"])
finish("S2")
