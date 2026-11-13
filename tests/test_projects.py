"""Offline tests for the projects registry loader (S0)."""
from pathlib import Path

import pytest
import yaml

from airflow_platform import projects

ROOT = Path(__file__).resolve().parents[1]


def _write(tmp_path: Path, raw: dict) -> Path:
    (tmp_path / "dags" / "a").mkdir(parents=True, exist_ok=True)
    (tmp_path / "dags" / "b").mkdir(parents=True, exist_ok=True)
    f = tmp_path / "projects" / "projects.yaml"
    f.parent.mkdir(exist_ok=True)
    f.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return f


def test_load_valid_registry(tmp_path):
    # The repo's own registry loads.
    repo = projects.load(ROOT / "projects" / "projects.yaml")
    assert [p.name for p in repo] == ["examples"]
    assert repo[0].dags.local == (ROOT / "dags" / "examples").resolve()

    # A full entry with view and task_link loads into dataclasses.
    f = _write(tmp_path, {"projects": [
        {"name": "a", "dags": {"local": "../dags/a"}},
        {"name": "b-2", "dags": {"local": "../dags/b", "git": {"repo_url": "https://example.invalid/r", "tracking_ref": "main"}},
         "view": {"label": "B", "url": "http://localhost:8501"},
         "task_link": {"label": "Open", "url_template": "http://x/?r={run_id}&d={dag_id}&t={task_id}", "dag_prefix": "b_"}},
    ]})
    got = projects.load(f)
    assert [p.name for p in got] == ["a", "b-2"]
    assert got[0].view is None and got[0].task_link is None
    assert got[1].view == projects.View("B", "http://localhost:8501")
    assert got[1].task_link.dag_prefix == "b_"
    assert got[1].dags.git["tracking_ref"] == "main"


def test_duplicate_names_rejected(tmp_path):
    raw = {"projects": [{"name": "a", "dags": {"local": "../dags/a"}},
                        {"name": "a", "dags": {"local": "../dags/b"}}]}
    f = _write(tmp_path, raw)
    errors = projects.validate(raw, base_dir=f.parent)
    assert len(errors) == 1 and "'a'" in errors[0] and "name" in errors[0] and "duplicate" in errors[0]
    with pytest.raises(ValueError, match="duplicate"):
        projects.load(f)


def test_bad_name_rejected(tmp_path):
    raw = {"projects": [{"name": "Bad_Name", "dags": {"local": "../dags/a"}}]}
    f = _write(tmp_path, raw)
    errors = projects.validate(raw, base_dir=f.parent)
    assert errors and "'name'" in errors[0]


def test_unknown_placeholder_rejected(tmp_path):
    raw = {"projects": [{"name": "a", "dags": {"local": "../dags/a"},
                         "task_link": {"label": "L", "url_template": "http://x/?r={run_id}&u={user}", "dag_prefix": "a_"}}]}
    f = _write(tmp_path, raw)
    errors = projects.validate(raw, base_dir=f.parent)
    assert len(errors) == 1
    assert "'a'" in errors[0] and "task_link.url_template" in errors[0] and "user" in errors[0]


def test_missing_local_path_names_project(tmp_path):
    raw = {"projects": [{"name": "ghost", "dags": {"local": "../dags/nope"}}]}
    f = _write(tmp_path, raw)
    errors = projects.validate(raw, base_dir=f.parent)
    assert len(errors) == 1 and "'ghost'" in errors[0] and "dags.local" in errors[0]


def test_task_link_needs_prefix(tmp_path):
    for prefix in (None, "", "  "):
        link = {"label": "L", "url_template": "http://x/{run_id}"}
        if prefix is not None:
            link["dag_prefix"] = prefix
        raw = {"projects": [{"name": "a", "dags": {"local": "../dags/a"}, "task_link": link}]}
        f = _write(tmp_path, raw)
        errors = projects.validate(raw, base_dir=f.parent)
        assert len(errors) == 1 and "'a'" in errors[0] and "task_link.dag_prefix" in errors[0]


def test_render_is_stubbed_until_s3():
    with pytest.raises(NotImplementedError):
        projects.render_bundles([])
    with pytest.raises(NotImplementedError):
        projects.render_compose_override([])
