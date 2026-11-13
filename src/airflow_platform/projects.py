"""Load and validate `projects/projects.yaml` (docs/spec.md §6).

Pure functions only: no Docker, no network, no Airflow import.
Renders the DAG bundle config and the compose override (S3); stack.py writes them to disk.
"""
from __future__ import annotations

import json
import re
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

NAME_RE = re.compile(r"^[a-z0-9-]+$")
ALLOWED_PLACEHOLDERS = frozenset({"run_id", "run_id_safe", "dag_id", "task_id"})


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
                                f"{bad}; allowed: {{run_id}}, {{run_id_safe}}, {{dag_id}}, {{task_id}}"
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
# Airflow 3.x DAG bundles (see NOTES.md, S3): config key [dag_processor] dag_bundle_config_list,
# a JSON list of {"name", "classpath", "kwargs"}. Every component that runs or parses DAG code
# reads it: dag-processor (parses), scheduler (LocalExecutor runs the task supervisors), triggerer,
# and the api-server (instantiates bundles for their view URLs). They all get the env var and the mounts.

CONTAINER_ROOT = "/opt/airflow/projects"
REGISTRY_IN_CONTAINER = f"{CONTAINER_ROOT}/projects.yaml"
LOCAL_BUNDLE = "airflow.dag_processing.bundles.local.LocalDagBundle"
GIT_BUNDLE = "airflow.providers.git.bundles.git.GitDagBundle"  # needs apache-airflow-providers-git
GIT_KWARGS = ("repo_url", "tracking_ref", "subdir", "git_conn_id", "refresh_interval")
BUNDLE_SERVICES = ("airflow-apiserver", "airflow-scheduler", "airflow-dag-processor", "airflow-triggerer")
BUNDLE_ENV = "AIRFLOW__DAG_PROCESSOR__DAG_BUNDLE_CONFIG_LIST"


def container_path(name: str) -> str:
    return f"{CONTAINER_ROOT}/{name}"


def render_bundles(projects: list[Project], target: str = "local") -> list[dict[str, Any]]:
    """The dag_bundle_config_list entries: a LocalDagBundle per project (local), or a GitDagBundle
    per project that has `dags.git` (cloud; local-only projects are skipped)."""
    if target == "local":
        return [{"name": p.name, "classpath": LOCAL_BUNDLE, "kwargs": {"path": container_path(p.name)}}
                for p in projects]
    if target == "cloud":
        out = []
        for p in projects:
            if not p.dags.git:
                continue
            kwargs = {k: p.dags.git[k] for k in GIT_KWARGS if k in p.dags.git}
            kwargs.setdefault("tracking_ref", "main")
            out.append({"name": p.name, "classpath": GIT_BUNDLE, "kwargs": kwargs})
        return out
    raise ValueError(f"unknown target {target!r}; expected 'local' or 'cloud'")


def render_env(projects: list[Project], target: str = "local") -> str:
    """stack/.env.generated: one line, the bundle list as compact JSON in a literal (single-quoted) value."""
    value = json.dumps(render_bundles(projects, target), separators=(",", ":"))
    if "'" in value:
        raise ValueError("bundle config must not contain a single quote")
    return f"# GENERATED by `python -m airflow_platform.stack render`; do not edit.\n{BUNDLE_ENV}='{value}'\n"


def _posix(path: str | Path) -> str:
    return Path(path).resolve().as_posix()


def render_compose_override(projects: list[Project], registry_dir: str | Path,
                            registry_file: str = "projects.yaml") -> dict[str, Any]:
    """stack/compose.projects.yaml: a read-only bind mount per project plus the registry file,
    into every service that reads bundles. The bundle list comes from the generated env file."""
    volumes = [f"{_posix(p.dags.local)}:{container_path(p.name)}:ro" for p in projects]
    volumes.append(f"{_posix(Path(registry_dir) / registry_file)}:{REGISTRY_IN_CONTAINER}:ro")
    env = {BUNDLE_ENV: f"${{{BUNDLE_ENV}:?run python -m airflow_platform.stack render}}"}
    return {"services": {s: {"environment": dict(env), "volumes": list(volumes)} for s in BUNDLE_SERVICES}}
