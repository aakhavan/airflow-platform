"""Project views and task links from the projects registry (docs/spec.md §7, ADR 0003).

Pure, stdlib only, no Airflow import. The functions between the COPY markers are copied verbatim
into plugins/project_views/__init__.py (the plugin can't import this package: the host package is
never installed into the Airflow image). tests/test_views.py asserts both copies are identical.

Projects are the raw YAML entries (dicts) or `projects.Project` objects; `_get` reads either.
"""
from __future__ import annotations

import string
import urllib.parse

# --- COPY START ---------------------------------------------------------------------------


def _get(obj, key):
    """A field of a registry entry: a dict key or an attribute (None when missing)."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def registry_errors(raw):
    """Errors in the fields the views plugin uses (names, view, task_link); empty when usable.
    No path checks: the plugin runs in a container where the host paths don't exist."""
    if not isinstance(raw, dict) or not isinstance(raw.get("projects"), list):
        return ["registry: top-level 'projects' must be a list"]
    errors = []
    for i, p in enumerate(raw["projects"]):
        if not isinstance(p, dict) or not isinstance(p.get("name"), str) or not p.get("name"):
            errors.append(f"projects[{i}]: field 'name' is required")
            continue
        view, link = p.get("view"), p.get("task_link")
        if view is not None and not (isinstance(view, dict) and all(
                isinstance(view.get(k), str) and view.get(k) for k in ("label", "url"))):
            errors.append(f"project '{p['name']}': field 'view' needs label and url")
        if link is not None:
            if not (isinstance(link, dict) and all(
                    isinstance(link.get(k), str) and link.get(k).strip()
                    for k in ("label", "url_template", "dag_prefix"))):
                errors.append(f"project '{p['name']}': field 'task_link' needs label, url_template and dag_prefix")
                continue
            try:
                fields = {f for _, f, _, _ in string.Formatter().parse(link["url_template"]) if f is not None}
            except ValueError as exc:
                errors.append(f"project '{p['name']}': field 'task_link.url_template' is malformed: {exc}")
                continue
            if fields - {"run_id", "dag_id", "task_id"}:
                errors.append(f"project '{p['name']}': field 'task_link.url_template' has unknown placeholders")
    return errors


def views_for(projects):
    """external_views entries: per project with a `view`, a nav entry (category browse) and a DAG tab.
    Both iframe the project's UI (url_route set). A DAG tab can't be limited to some DAGs in 3.3."""
    out = []
    for p in projects:
        view = _get(p, "view")
        if not view:
            continue
        name, label, url = _get(p, "name"), _get(view, "label"), _get(view, "url")
        out.append({"name": label, "href": url, "destination": "nav", "category": "browse",
                    "url_route": name})
        out.append({"name": label, "href": url, "destination": "dag", "url_route": f"{name}-dag"})
    return out


def link_for(project, dag_id, run_id, task_id):
    """The task link URL for one task instance; "" when the DAG isn't the project's (prefix) or
    the project has no task_link. Values are URL-quoted."""
    link = _get(project, "task_link")
    prefix = _get(link, "dag_prefix")
    if not prefix or not str(dag_id).startswith(prefix):
        return ""
    q = lambda v: urllib.parse.quote(str(v), safe="")  # noqa: E731
    return _get(link, "url_template").format(dag_id=q(dag_id), run_id=q(run_id), task_id=q(task_id))


# --- COPY END -----------------------------------------------------------------------------

COPIED = ("_get", "registry_errors", "views_for", "link_for")
