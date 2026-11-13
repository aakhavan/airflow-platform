"""Offline tests for the S1 stack files and the status helpers (no Docker, no network, no Airflow)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from airflow_platform import stack

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _compose() -> dict:
    return yaml.safe_load((ROOT / "stack" / "compose.yaml").read_text(encoding="utf-8"))


def _common_env(svc: dict) -> dict:
    return svc.get("environment") or {}


def test_compose_has_no_celery_services():
    c = _compose()
    services = set(c["services"])
    assert not services & {"redis", "airflow-worker", "flower", "airflow-cli"}
    assert set(stack.EXPECTED) <= services
    assert c["name"] == "airflow_platform"
    text = (ROOT / "stack" / "compose.yaml").read_text(encoding="utf-8")
    assert "CELERY" not in text.upper()
    assert "redis" not in text.lower()


def test_every_service_has_healthcheck():
    for name, svc in _compose()["services"].items():
        hc = svc.get("healthcheck") or {}
        assert hc.get("test"), f"{name} has no healthcheck"


def test_executor_is_local():
    c = _compose()
    for name, svc in c["services"].items():
        if name == "postgres":
            continue
        env = _common_env(svc)
        assert env["AIRFLOW__CORE__EXECUTOR"] == "LocalExecutor", name
        assert str(env["AIRFLOW__CORE__LOAD_EXAMPLES"]).lower() == "false", name
        assert svc["image"] == "airflow-platform:local", name
        assert svc["build"] == "../image", name
    ports = c["services"]["airflow-apiserver"]["ports"]
    assert ports == ["${AIRFLOW_PORT:-8080}:8080"]


def test_dockerfile_installs_with_constraints():
    d = (ROOT / "image" / "Dockerfile").read_text(encoding="utf-8")
    version = re.search(r"^ARG AIRFLOW_VERSION=(\d+\.\d+\.\d+)$", d, re.M)
    assert version and version.group(1).startswith("3.3.")
    assert "FROM apache/airflow:${AIRFLOW_VERSION}-python3.12" in d
    assert "--constraint" in d
    assert ("https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-3.12.txt") in d
    assert "-r /requirements.txt" in d
    # The version appears in exactly one ARG default.
    assert len(re.findall(r"\d+\.\d+\.\d+", d)) == 1
    req = [l.strip() for l in (ROOT / "image" / "requirements.txt").read_text(encoding="utf-8").splitlines()]
    pkgs = [l for l in req if l and not l.startswith("#")]
    assert pkgs and all(p.startswith("apache-airflow-providers-") for p in pkgs)
    assert all(not re.search(r"[=<>~]", p) for p in pkgs), "providers stay unpinned"
    versions = yaml.safe_load((ROOT / "stack" / "versions.yaml").read_text(encoding="utf-8"))
    assert versions["airflow"]["version"] == version.group(1)


def test_status_line_shape():
    sample = (FIXTURES / "compose_ps.json").read_text(encoding="utf-8")
    services = stack.parse_ps(sample)
    assert set(stack.EXPECTED) <= set(services)
    assert services["airflow-init"] == "ok"
    line = stack.status_line(services, "3.3.2", "http://localhost:8080",
                             stack.parse_mem_mb("512.5MiB / 7.6GiB\n1.2GiB / 7.6GiB\n800KiB / 7.6GiB\n"))
    assert list(line) == ["up", "services", "airflow_version", "url", "mem_mb"]
    assert line["up"] is True
    assert isinstance(line["mem_mb"], int) and line["mem_mb"] == 1742
    assert json.loads(json.dumps(line)) == line
    # One unhealthy service, or a missing one, means not up.
    assert stack.status_line({**services, "airflow-scheduler": "unhealthy"}, "", "", 0)["up"] is False
    assert stack.status_line({"postgres": "healthy"}, "", "", 0)["up"] is False


def test_parse_ps_handles_array_and_failed_init():
    rec = [{"Service": "airflow-init", "Name": "x", "State": "exited", "ExitCode": 1, "Health": ""},
           {"Service": "postgres", "Name": "y", "State": "running", "Health": "healthy"}]
    assert stack.parse_ps(json.dumps(rec)) == {"airflow-init": "exited(1)", "postgres": "healthy"}
    assert stack.container_names(json.dumps(rec)) == ["y"]
    assert stack.parse_ps("") == {}


def test_compose_args_adds_override_only_when_present():
    base = stack.compose_args(False)
    assert base[:4] == ["docker", "compose", "-p", "airflow_platform"]
    assert str(stack.OVERRIDE) not in base
    assert str(stack.OVERRIDE) in stack.compose_args(True)
    assert base[-2:] == ["--env-file", str(stack.ENV)]


def test_env_value():
    assert stack.env_value("A=1\nAIRFLOW_PORT=9090\n", "AIRFLOW_PORT", "8080") == "9090"
    assert stack.env_value("AIRFLOW_PORT=\n", "AIRFLOW_PORT", "8080") == "8080"
