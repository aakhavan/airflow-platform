"""S4: project views and task links (offline; the plugin is loaded against a stub airflow package)."""
from __future__ import annotations

import ast
import importlib.util
import logging
import sys
import types
from pathlib import Path

import pytest

from airflow_platform import views

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "project_views" / "__init__.py"
VIEWS = ROOT / "src" / "airflow_platform" / "views.py"

GOV = {"name": "governor", "view": {"label": "Governor", "url": "http://localhost:8501"},
       "task_link": {"label": "Open report", "url_template": "http://localhost:8501/Profiles?run_id={run_id}",
                     "dag_prefix": "governor_"}}
PLAIN = {"name": "examples"}


def test_views_for_nav_and_dag_tab():
    out = views.views_for([PLAIN, GOV])
    assert out == [
        {"name": "Governor", "href": "http://localhost:8501", "destination": "nav", "category": "browse",
         "url_route": "governor"},
        {"name": "Governor", "href": "http://localhost:8501", "destination": "dag", "url_route": "governor-dag"},
    ]


def test_link_for_matching_prefix():
    assert views.link_for(GOV, "governor_profile", "r1", "t") == "http://localhost:8501/Profiles?run_id=r1"


def test_link_for_other_dag_is_empty():
    assert views.link_for(GOV, "hello_workload", "r1", "t") == ""
    assert views.link_for(PLAIN, "governor_profile", "r1", "t") == ""


def test_link_values_are_quoted():
    p = {"name": "x", "task_link": {"label": "L", "url_template": "http://h/{dag_id}/{task_id}?run={run_id}",
                                    "dag_prefix": "x_"}}
    url = views.link_for(p, "x_d", "manual__2026-11-13T18:41:12.36+00:00", "a b/c&d")
    assert url == "http://h/x_d/a%20b%2Fc%26d?run=manual__2026-11-13T18%3A41%3A12.36%2B00%3A00"


def test_link_for_reads_dataclass_projects(tmp_path):
    from airflow_platform import projects
    (tmp_path / "d").mkdir()
    (tmp_path / "p.yaml").write_text(
        "projects:\n  - name: governor\n    dags: {local: d}\n"
        "    task_link: {label: R, url_template: 'http://h?r={run_id}', dag_prefix: governor_}\n", encoding="utf-8")
    [p] = projects.load(tmp_path / "p.yaml")
    assert views.link_for(p, "governor_x", "r", "t") == "http://h?r=r"


def _functions(path: Path) -> dict[str, str]:
    src = path.read_text(encoding="utf-8")
    return {n.name: ast.get_source_segment(src, n) for n in ast.parse(src).body
            if isinstance(n, ast.FunctionDef) and n.name in views.COPIED}


def test_plugin_copy_matches_views_module():
    ours, theirs = _functions(VIEWS), _functions(PLUGIN)
    assert set(ours) == set(views.COPIED)
    assert ours == theirs


def test_plugin_imports_only_allowed_modules():
    allowed = set(sys.stdlib_module_names) | {"yaml", "airflow", "__future__"}
    bad = []
    for node in ast.walk(ast.parse(PLUGIN.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mods = [node.module or ""] if node.level == 0 else ["<relative>"]
        else:
            continue
        bad += [m for m in mods if m.split(".")[0] not in allowed]
    assert not bad


@pytest.fixture
def stub_airflow(monkeypatch):
    airflow = types.ModuleType("airflow")
    pm = types.ModuleType("airflow.plugins_manager")
    sdk = types.ModuleType("airflow.sdk")

    class AirflowPlugin:
        name = None
        external_views: list = []
        global_operator_extra_links: list = []

    class BaseOperatorLink:
        name = ""

    pm.AirflowPlugin, sdk.BaseOperatorLink = AirflowPlugin, BaseOperatorLink
    airflow.plugins_manager, airflow.sdk = pm, sdk
    for name, mod in (("airflow", airflow), ("airflow.plugins_manager", pm), ("airflow.sdk", sdk)):
        monkeypatch.setitem(sys.modules, name, mod)


def _load_plugin(monkeypatch, registry: Path):
    monkeypatch.setenv("PLATFORM_PROJECTS_FILE", str(registry))
    spec = importlib.util.spec_from_file_location("project_views_under_test", PLUGIN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_broken_registry_registers_nothing(stub_airflow, monkeypatch, tmp_path, caplog):
    bad = tmp_path / "projects.yaml"
    bad.write_text("projects:\n  - name: governor\n    task_link: {label: R, url_template: 'http://h/{nope}', "
                   "dag_prefix: governor_}\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        mod = _load_plugin(monkeypatch, bad)
    assert mod.ProjectViewsPlugin.external_views == []
    assert mod.ProjectViewsPlugin.global_operator_extra_links == []
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1

    caplog.clear()
    bad.write_text("projects: [unclosed", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        mod = _load_plugin(monkeypatch, bad)
    assert mod.ProjectViewsPlugin.external_views == [] and len(caplog.records) == 1


def test_plugin_registers_views_and_links(stub_airflow, monkeypatch, tmp_path):
    reg = tmp_path / "projects.yaml"
    reg.write_text("projects:\n  - name: examples\n  - name: governor\n    view: {label: Governor, url: 'http://g'}\n"
                   "    task_link: {label: Open report, url_template: 'http://g/?r={run_id}', dag_prefix: governor_}\n",
                   encoding="utf-8")
    mod = _load_plugin(monkeypatch, reg)
    assert mod.ProjectViewsPlugin.name == "project_views"
    assert [v["destination"] for v in mod.ProjectViewsPlugin.external_views] == ["nav", "dag"]
    [link] = mod.ProjectViewsPlugin.global_operator_extra_links
    assert link.name == "Open report" and type(link).__name__ == "ProjectTaskLink_governor"
    key = types.SimpleNamespace(dag_id="governor_p", run_id="a:b", task_id="t")
    assert link.get_link(None, ti_key=key) == "http://g/?r=a%3Ab"
    key.dag_id = "hello_workload"
    assert link.get_link(None, ti_key=key) == ""


def test_link_for_run_id_safe():
    proj = {**GOV, "task_link": {**GOV["task_link"],
            "url_template": "http://localhost:8501/Profiles?run_id={run_id_safe}"}}
    url = views.link_for(proj, "governor_profile_raw", "manual__2026-11-13T20:14:31+00:00", "profile")
    assert url == "http://localhost:8501/Profiles?run_id=" + views.link_for(
        {**proj, "task_link": {**proj["task_link"], "url_template": "{run_id_safe}"}},
        "governor_profile_raw", "manual__2026-11-13T20:14:31+00:00", "profile")
    assert ":" not in url.split("run_id=", 1)[1]
    assert "manual__2026-11-13T20_14_31" in url
