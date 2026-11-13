"""Offline tests for the projects registry loader (S0) and the bundle/override rendering (S3)."""
import json
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
    assert [p.name for p in repo] == ["examples", "governor"]
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


# --- S3: rendering ---------------------------------------------------------------------------

GIT = {"repo_url": "https://example.invalid/r", "subdir": "airflow/dags", "tracking_ref": "main"}


def _registry(tmp_path: Path, names: list[str], git_for: tuple[str, ...] = ()) -> Path:
    entries = []
    for n in names:
        (tmp_path / "dags" / n).mkdir(parents=True, exist_ok=True)
        dags = {"local": f"../dags/{n}"}
        if n in git_for:
            dags["git"] = dict(GIT)
        entries.append({"name": n, "dags": dags})
    f = tmp_path / "reg" / "projects.yaml"
    f.parent.mkdir(exist_ok=True)
    f.write_text(yaml.safe_dump({"projects": entries}), encoding="utf-8")
    return f


def _mounts(override: dict) -> list[str]:
    return [v for svc in override["services"].values() for v in svc["volumes"]]


def test_render_local_bundle_per_project(tmp_path):
    ps = projects.load(_registry(tmp_path, ["alpha", "beta-2"]))
    bundles = projects.render_bundles(ps)
    assert bundles == [
        {"name": "alpha", "classpath": "airflow.dag_processing.bundles.local.LocalDagBundle",
         "kwargs": {"path": "/opt/airflow/projects/alpha"}},
        {"name": "beta-2", "classpath": "airflow.dag_processing.bundles.local.LocalDagBundle",
         "kwargs": {"path": "/opt/airflow/projects/beta-2"}},
    ]
    env = projects.render_env(ps)
    line = [l for l in env.splitlines() if not l.startswith("#")][0]
    key, value = line.split("=", 1)
    assert key == "AIRFLOW__DAG_PROCESSOR__DAG_BUNDLE_CONFIG_LIST"
    assert value[0] == value[-1] == "'" and json.loads(value[1:-1]) == bundles
    # The repo's own registry renders the examples and governor bundles.
    repo = projects.render_bundles(projects.load(ROOT / "projects" / "projects.yaml"))
    assert [b["name"] for b in repo] == ["examples", "governor"]


def test_render_cloud_uses_git_bundle_and_skips_local_only(tmp_path):
    ps = projects.load(_registry(tmp_path, ["local-only", "gitty"], git_for=("gitty",)))
    bundles = projects.render_bundles(ps, target="cloud")
    assert bundles == [{"name": "gitty", "classpath": "airflow.providers.git.bundles.git.GitDagBundle",
                        "kwargs": GIT}]
    with pytest.raises(ValueError, match="target"):
        projects.render_bundles(ps, target="mars")


def test_override_mounts_are_read_only(tmp_path):
    f = _registry(tmp_path, ["alpha", "beta"])
    ov = projects.render_compose_override(projects.load(f), f.parent)
    assert set(ov["services"]) >= {"airflow-scheduler", "airflow-dag-processor", "airflow-triggerer"}
    for svc in ov["services"].values():
        targets = [v.rsplit(":", 2)[1] for v in svc["volumes"]]
        assert targets == ["/opt/airflow/projects/alpha", "/opt/airflow/projects/beta",
                           "/opt/airflow/projects/projects.yaml"]
        assert "AIRFLOW__DAG_PROCESSOR__DAG_BUNDLE_CONFIG_LIST" in svc["environment"]
    assert all(v.endswith(":ro") for v in _mounts(ov))
    assert not any("docker.sock" in v for v in _mounts(ov))


def test_override_paths_use_forward_slashes(tmp_path):
    f = _registry(tmp_path, ["alpha"])
    ov = projects.render_compose_override(projects.load(f), f.parent)
    for v in _mounts(ov):
        assert "\\" not in v
        source = v.rsplit(":", 2)[0]
        assert Path(source).is_absolute()
    first = ov["services"]["airflow-dag-processor"]["volumes"]
    assert first[0].rsplit(":", 2)[0] == (tmp_path / "dags" / "alpha").resolve().as_posix()
    assert first[-1].rsplit(":", 2)[0] == f.resolve().as_posix()


def test_adding_a_project_changes_only_generated_output(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    one = _registry(a, ["examples"])
    two = _registry(b, ["examples", "zz-new"])
    out1 = (projects.render_bundles(projects.load(one)), projects.render_compose_override(projects.load(one), one.parent))
    out2 = (projects.render_bundles(projects.load(two)), projects.render_compose_override(projects.load(two), two.parent))
    assert out1 != out2
    assert [x["name"] for x in out2[0]] == ["examples", "zz-new"]
    assert out2[0][0] == out1[0][0]  # existing bundle unchanged
    assert set(out1[1]["services"]) == set(out2[1]["services"])
    assert any("/opt/airflow/projects/zz-new:ro" in v for v in _mounts(out2[1]))
    # No platform code or static config names a project: names come only from the registry.
    for rel in ("src/airflow_platform/projects.py", "src/airflow_platform/stack.py", "stack/compose.yaml"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "zz-new" not in text and "examples" not in text.replace("dags/examples", ""), rel
