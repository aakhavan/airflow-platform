"""S4 acceptance: project views plugin registers nav/dag views and task links from projects.yaml."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT, check, finish, guarded, no_secrets, pytest_check, read, stack, tail, trigger_and_wait  # noqa: E402


def static():
    src = read("plugins/project_views/__init__.py")
    check("plugin exists", bool(src))
    for bad in ("fastapi_apps", "react_apps", "flask", "appbuilder"):
        check(f"plugin has no {bad}", bad not in src.lower())
    check("plugin uses global_operator_extra_links", "global_operator_extra_links" in src)
    no_secrets()


def live():
    _, r = stack("up", timeout=900)
    check("stack up with plugin", r.returncode == 0, tail(r))
    p, r = stack("plugins", timeout=120)
    if not check("stack plugins prints JSON", p is not None, tail(r)):
        return
    text = json.dumps(p)
    check("project_views plugin loaded", "project_views" in text, text[:200])
    check("examples nav view registered", "localhost:8080/docs" in text, text[:200])
    res = trigger_and_wait("hello_workload")
    if res.get("run_id"):
        l, r = stack("links", "hello_workload", res["run_id"], "hello", timeout=120)
        check("task link resolves for the run", bool(l) and any("localhost:8080/docs" in str(v) for v in (l.get("links") or {}).values()),
              str(l or tail(r))[:200])


guarded(static)
guarded(live)
guarded(pytest_check, "tests", ["test_views_for_nav_and_dag_tab", "test_link_for_matching_prefix", "test_link_for_other_dag_is_empty",
                                "test_link_values_are_quoted", "test_plugin_copy_matches_views_module",
                                "test_plugin_imports_only_allowed_modules", "test_broken_registry_registers_nothing"])
finish("S4")
