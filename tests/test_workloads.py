"""Offline tests for the S2 workload pattern (no Docker, no network, no Airflow import)."""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import yaml

from airflow_platform import stack

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SOCKET = "/var/run/docker.sock"
# Fields of TriggerDAGRunPostBody on the running 3.3.2 server's /openapi.json (additionalProperties: false).
TRIGGER_FIELDS = {"dag_run_id", "data_interval_start", "data_interval_end", "logical_date", "run_after",
                  "conf", "note", "partition_key"}


def _api() -> dict:
    return json.loads((FIXTURES / "api_v2_hello.json").read_text(encoding="utf-8"))


def _imports(path: Path) -> list[str]:
    mods = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            mods += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"{path.name}: relative import"
            mods.append(node.module or "")
    return mods


def test_hello_dag_imports_only_allowed_modules():
    files = list((ROOT / "dags").rglob("*.py"))
    assert ROOT / "dags" / "examples" / "hello_workload.py" in files
    allowed = set(sys.stdlib_module_names) | {"airflow", "__future__"}
    bad = [f"{f.name}:{m}" for f in files for m in _imports(f) if m.split(".")[0] not in allowed]
    assert not bad, bad
    text = (ROOT / "dags" / "examples" / "hello_workload.py").read_text(encoding="utf-8")
    for needle in ('dag_id="hello_workload"', "schedule=None", "catchup=False", 'tags=["platform"]',
                   'task_id="hello"', 'image="airflow-platform/hello:local"', "mount_tmp_dir=False",
                   'auto_remove="success"', '"docker_url"', '"tcp://docker-proxy:2375"'):
        assert needle in text, needle


def test_no_airflow_service_mounts_docker_socket():
    text = (ROOT / "stack" / "compose.yaml").read_text(encoding="utf-8")
    assert text.count(SOCKET) == 1
    services = yaml.safe_load(text)["services"]
    for name, svc in services.items():
        mounts = [str(v) for v in svc.get("volumes") or []]
        if name == "docker-proxy":
            assert mounts == [f"{SOCKET}:/run/docker.sock:ro"]
            assert svc["environment"]["SOCKET_PATH"] == "/run/docker.sock"
            assert svc["image"].startswith("tecnativa/docker-socket-proxy:")
            assert not svc["image"].endswith(":latest")
            assert "ports" not in svc, "the proxy has no host port"
            assert svc["healthcheck"]["test"]
        else:
            assert not any("docker.sock" in m for m in mounts), name
    versions = yaml.safe_load((ROOT / "stack" / "versions.yaml").read_text(encoding="utf-8"))
    assert versions["images"]["docker_proxy"] == services["docker-proxy"]["image"]
    assert "docker-proxy" in stack.EXPECTED


def test_trigger_payload_shape():
    body = stack.trigger_payload({"source": "test"})
    assert set(body) <= TRIGGER_FIELDS
    assert body == {"logical_date": None, "conf": {"source": "test"}}
    assert stack.trigger_payload() == {"logical_date": None, "conf": {}}
    line = stack.run_result("hello_workload", _api()["trigger_response"])
    assert list(line) == ["dag_id", "run_id", "state"]
    assert line["dag_id"] == "hello_workload" and line["state"] == "queued"
    assert line["run_id"].startswith("manual__")
    assert json.loads(json.dumps(line)) == line


def test_wait_parses_states():
    api = _api()
    done = stack.run_result("hello_workload", api["run_response"])
    assert done["state"] == "success" and stack.is_terminal(done["state"])
    for state in ("queued", "running"):
        assert not stack.is_terminal(stack.run_result("d", {"state": state})["state"])
    assert stack.is_terminal("failed")
    assert stack.run_result("d", {})["state"] == "unknown"
    assert stack.try_number(api["task_instance"]) == 1
    assert stack.try_number({"try_number": 0}) == 1
    lines = stack.log_lines(api["log_response"])
    assert "hello from a workload" in lines
    result = [json.loads(l) for l in lines if l.startswith('{"workload"')]
    assert result and result[0]["workload"] == "hello" and result[0]["ok"] is True
    assert stack.log_lines({"content": "a\nb"}) == ["a", "b"]


def test_import_errors_and_workload_images():
    assert stack.count_import_errors("[]\n") == 0
    assert stack.count_import_errors('noise\n[{"filename": "a.py"}, {"filename": "b.py"}]') == 2
    images = stack.workload_images(ROOT / "workloads")
    assert ("airflow-platform/hello:local", ROOT / "workloads" / "hello") in images
    assert stack.workload_images(ROOT / "no-such-dir") == []
    dockerfile = (ROOT / "workloads" / "hello" / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:3.12." in dockerfile and "-slim" in dockerfile
