"""S5: governor as the first project (offline; reads the repo's registry and stack/.env.example)."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

from airflow_platform import views

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "projects" / "projects.yaml"
ENV_EXAMPLE = ROOT / "stack" / ".env.example"
# A1's Streamlit page in the governor worktree (read only; absent on machines without it, e.g. CI).
PAGE = ROOT.parent / "governor-airflow" / "apps" / "streamlit" / "pages" / "4_Profiles.py"

# Every name stack/.env.example may set, with the only value it may have: the documented local
# defaults of the official Airflow 3.3.2 compose file and of governor's test bed.
ALLOWED_ENV = {
    "AIRFLOW_UID": "50000",
    "AIRFLOW_PORT": "8080",
    "_AIRFLOW_WWW_USER_USERNAME": "airflow",
    "_AIRFLOW_WWW_USER_PASSWORD": "airflow",
    "FERNET_KEY": "",
    "AIRFLOW_VAR_DOCKER_URL": "tcp://docker-proxy:2375",
    "AIRFLOW_VAR_GOVERNOR_DATA_VOLUME": "governor-airflow_governor-data",  # worktree; governor_governor-data after the merge
    "AIRFLOW_VAR_GOVERNOR_PG_HOST": "host.docker.internal",
    "AIRFLOW_VAR_GOVERNOR_PG_PORT": "55432",
    "AIRFLOW_VAR_GOVERNOR_PG_DB": "shop",
    "AIRFLOW_VAR_GOVERNOR_BUILD_USER": "governor_build",
    "AIRFLOW_VAR_GOVERNOR_BUILD_PASSWORD": "governor_build_local",
}


def _registry() -> dict:
    return yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))


def _governor() -> dict:
    [gov] = [p for p in _registry()["projects"] if p.get("name") == "governor"]
    return gov


def _env_example() -> dict[str, str]:
    out = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, value = line.partition("=")
        assert sep, f"not NAME=value: {line!r}"
        assert name not in out, f"duplicate {name}"
        out[name] = value.strip("\"")  # compose env files allow quoted values
    return out


def test_registry_has_governor_with_view_and_link():
    raw = _registry()
    assert views.registry_errors(raw) == []
    assert [p["name"] for p in raw["projects"]] == ["examples", "governor"]
    # The S4 placeholder view/link on examples is gone.
    examples = raw["projects"][0]
    assert "view" not in examples and "task_link" not in examples

    gov = _governor()
    assert gov["dags"]["local"] == "../../governor-airflow/airflow/dags"
    assert gov["dags"]["git"]["subdir"] == "airflow/dags"
    assert gov["view"] == {"label": "Governor", "url": "http://localhost:8501"}
    assert gov["task_link"]["dag_prefix"] == "governor_"

    out = views.views_for(raw["projects"])
    assert {(v["destination"], v["href"]) for v in out} == {("nav", "http://localhost:8501"),
                                                             ("dag", "http://localhost:8501")}
    assert views.link_for(gov, "hello_workload", "r", "hello") == ""


def test_governor_link_targets_profiles_page():
    gov = _governor()
    run_id = "manual__2026-11-13T19:14:22.354427+00:00"
    url = views.link_for(gov, "governor_profile_raw", run_id, "profile")
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}" == gov["view"]["url"]
    assert parts.path == "/Profiles"
    # the file-safe run id: the DAG names the profile file with ":" replaced by "_"
    assert parse_qs(parts.query) == {"run_id": [run_id.replace(":", "_")]}  # quoted out, exact in

    if not PAGE.is_file():
        pytest.skip("governor worktree not present; the page-name check needs it")
    # Streamlit's URL path for pages/<n>_<Name>.py is /<Name>; the page reads the run_id query param.
    assert "/" + re.sub(r"^\d+_", "", PAGE.stem) == parts.path
    assert re.search(r"query_params\.get\(\s*[\"']run_id[\"']\s*\)", PAGE.read_text(encoding="utf-8"))


def test_env_example_has_no_values_beyond_documented_defaults():
    env = _env_example()
    extra = sorted(set(env) - set(ALLOWED_ENV))
    assert not extra, f"undocumented names in .env.example: {extra}"
    wrong = sorted(k for k, v in env.items() if v != ALLOWED_ENV[k])
    assert not wrong, f"values other than the documented defaults: {wrong}"
    # The governor DAG's Variables are all set, each through AIRFLOW_VAR_<NAME>.
    for var in ("docker_url", "governor_data_volume", "governor_pg_host", "governor_pg_port", "governor_pg_db",
                "governor_build_user", "governor_build_password"):
        assert f"AIRFLOW_VAR_{var.upper()}" in env
