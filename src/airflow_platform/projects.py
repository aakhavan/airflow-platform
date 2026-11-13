"""Load and validate `projects/projects.yaml` (docs/spec.md §6).

Pure functions only: no Docker, no network, no Airflow import.
Rendering (bundle config JSON, compose override) arrives in S3.
"""
from __future__ import annotations

import re
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

NAME_RE = re.compile(r"^[a-z0-9-]+$")
ALLOWED_PLACEHOLDERS = frozenset({"run_id", "dag_id", "task_id"})


@dataclass(frozen=True)
class DagSource:
    local: Path                      # resolved absolute path to the project's DAG folder
    git: dict[str, Any] | None = None  # cloud only; documented, rendered in S3 with --target cloud


@dataclass(frozen=True)
class View:
    label: str
    url: str


@dataclass(frozen=True)
class TaskLink:
    label: str
    url_template: str
    dag_prefix: str


@dataclass(frozen=True)
class Project:
    name: str
    dags: DagSource
    view: View | None = None
    task_link: TaskLink | None = None


def _placeholders(template: str) -> list[str]:
    """Field names used in a str.format template. Raises ValueError on malformed braces."""
    return [field for _, field, _, _ in string.Formatter().parse(template) if field is not None]


def validate(raw: Any, base_dir: str | Path | None = None) -> list[str]:
    """Return a list of errors (empty when valid). Each error names the project and the field.

    `base_dir` is the directory of the YAML file; `dags.local` is resolved against it
    (defaults to the current directory).
    """
    base = Path(base_dir) if base_dir is not None else Path.cwd()
    if not isinstance(raw, dict) or not isinstance(raw.get("projects"), list):
        return ["registry: top-level 'projects' must be a list"]

    errors: list[str] = []
    seen: set[str] = set()
    for i, p in enumerate(raw["projects"]):
        if not isinstance(p, dict):
            errors.append(f"projects[{i}]: entry must be a mapping")
            continue
        name = p.get("name")
        label = f"project '{name}'" if isinstance(name, str) and name else f"projects[{i}]"

        # name
        if not isinstance(name, str) or not NAME_RE.match(name):
            errors.append(f"{label}: field 'name' must match [a-z0-9-]+ (got {name!r})")
        elif name in seen:
            errors.append(f"{label}: field 'name' is a duplicate")
        else:
            seen.add(name)

        # dags.local
        dags = p.get("dags")
        local = dags.get("local") if isinstance(dags, dict) else None
        if not isinstance(local, str) or not local:
            errors.append(f"{label}: field 'dags.local' is required")
        elif not (base / local).is_dir():
            errors.append(f"{label}: field 'dags.local' path does not exist: {local}")
        if isinstance(dags, dict) and "git" in dags and not isinstance(dags["git"], dict):
            errors.append(f"{label}: field 'dags.git' must be a mapping")

        # view
        view = p.get("view")
        if view is not None:
            if not isinstance(view, dict):
                errors.append(f"{label}: field 'view' must be a mapping")
            else:
                for key in ("label", "url"):
                    if not isinstance(view.get(key), str) or not view.get(key):
                        errors.append(f"{label}: field 'view.{key}' is required")

        # task_link
        link = p.get("task_link")
        if link is not None:
            if not isinstance(link, dict):
                errors.append(f"{label}: field 'task_link' must be a mapping")
            else:
                if not isinstance(link.get("label"), str) or not link.get("label"):
                    errors.append(f"{label}: field 'task_link.label' is required")
                tmpl = link.get("url_template")
                if not isinstance(tmpl, str) or not tmpl:
                    errors.append(f"{label}: field 'task_link.url_template' is required")
                else:
                    try:
                        bad = sorted({f for f in _placeholders(tmpl) if f not in ALLOWED_PLACEHOLDERS})
                    except ValueError as exc:
                        errors.append(f"{label}: field 'task_link.url_template' is malformed: {exc}")
                    else:
                        if bad:
                            errors.append(
                                f"{label}: field 'task_link.url_template' has unknown placeholder(s) "
                                f"{bad}; allowed: {{run_id}}, {{dag_id}}, {{task_id}}"
                            )
                prefix = link.get("dag_prefix")
                if not isinstance(prefix, str) or not prefix.strip():
                    errors.append(f"{label}: field 'task_link.dag_prefix' must be non-empty when task_link is set")
    return errors


def _build(p: dict[str, Any], base: Path) -> Project:
    dags = p["dags"]
    view = p.get("view")
    link = p.get("task_link")
    return Project(
        name=p["name"],
        dags=DagSource(local=(base / dags["local"]).resolve(), git=dags.get("git")),
        view=View(label=view["label"], url=view["url"]) if view else None,
        task_link=TaskLink(label=link["label"], url_template=link["url_template"], dag_prefix=link["dag_prefix"])
        if link else None,
    )


def load(path: str | Path) -> list[Project]:
    """Read, validate and return the registry. Raises ValueError listing every error."""
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    errors = validate(raw, base_dir=path.parent)
    if errors:
        raise ValueError(f"{path}: invalid projects registry:\n  " + "\n  ".join(errors))
    return [_build(p, path.parent) for p in raw["projects"]]


# --- Rendering (S3) -------------------------------------------------------------------------

def render_bundles(projects: list[Project], target: str = "local") -> str:
    """S3: AIRFLOW__DAG_PROCESSOR__DAG_BUNDLE_CONFIG_LIST JSON (LocalDagBundle per project)."""
    raise NotImplementedError("render_bundles arrives in S3")


def render_compose_override(projects: list[Project]) -> str:
    """S3: stack/compose.projects.yaml with a read-only bind mount per project."""
    raise NotImplementedError("render_compose_override arrives in S3")
