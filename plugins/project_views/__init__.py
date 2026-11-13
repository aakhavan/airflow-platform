"""project_views: Airflow plugin that turns projects.yaml into external views and task links.

docs/spec.md §7, ADR 0003. Reads /opt/airflow/projects/projects.yaml (env PLATFORM_PROJECTS_FILE
overrides). For each project with a `view`: a nav entry (category browse) and a DAG tab, both
iframing the project's UI. For each project with a `task_link`: one BaseOperatorLink registered via
global_operator_extra_links. On any error reading or validating the file it logs one warning and
registers nothing, so a broken registry never breaks Airflow.

Imports: stdlib, yaml and airflow only. The functions between the COPY markers are a verbatim copy
of src/airflow_platform/views.py (the host package is not installed in the image); a test keeps
the two identical.
"""
from __future__ import annotations

import logging
import os
import string
import urllib.parse
from pathlib import Path

import yaml
from airflow.plugins_manager import AirflowPlugin

try:  # Airflow 3.x task SDK
    from airflow.sdk import BaseOperatorLink
except ImportError:  # pragma: no cover - older layout
    from airflow.models.baseoperatorlink import BaseOperatorLink

log = logging.getLogger(__name__)
DEFAULT_FILE = "/opt/airflow/projects/projects.yaml"

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


def _link_class(project):
    """One BaseOperatorLink subclass for a project's task_link (3.x: get_link(self, operator, *, ti_key))."""
    label = project["task_link"]["label"]

    class ProjectTaskLink(BaseOperatorLink):
        name = label

        def get_link(self, operator, *, ti_key):
            return link_for(project, ti_key.dag_id, ti_key.run_id, ti_key.task_id)

    # A stable, unique class name per project (the 3.x xcom_key is derived from the class name).
    cls_name = "ProjectTaskLink_" + "".join(c if c.isalnum() else "_" for c in project["name"])
    ProjectTaskLink.__name__ = ProjectTaskLink.__qualname__ = cls_name
    return ProjectTaskLink


def build(path):
    """(external_views, operator links) from the registry at `path`; ([], []) plus one warning on error."""
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        errors = registry_errors(raw)
        if errors:
            raise ValueError("; ".join(errors))
        projects = raw["projects"]
        links = [_link_class(p)() for p in projects if p.get("task_link")]
        return views_for(projects), links
    except Exception as exc:  # noqa: BLE001 - a broken registry must never break Airflow
        log.warning("project_views: registry %s unusable, registering nothing: %s", path, exc)
        return [], []


_VIEWS, _LINKS = build(os.environ.get("PLATFORM_PROJECTS_FILE") or DEFAULT_FILE)


class ProjectViewsPlugin(AirflowPlugin):
    name = "project_views"
    external_views = _VIEWS
    global_operator_extra_links = _LINKS
