"""Local stack control: python -m airflow_platform.stack
up|down|status|render|trigger|wait|logs|plugins|links|compose-logs.

Every command prints one JSON line last. Docker output goes to logs/ (git-ignored).
Every subcommand takes --compose-project (default airflow_platform, the dev stack) and --port (default
AIRFLOW_PORT from stack/.env, else 8080), so a second stack (scripts/ci-local.ps1: airflow_platform_ci on 8081)
runs next to the dev stack without touching it.
The parsing helpers (parse_ps, parse_mem_mb, status_line) are pure and tested offline.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

from airflow_platform import projects as registry

ROOT = Path(__file__).resolve().parents[2]
STACK = ROOT / "stack"
LOGS = ROOT / "logs"
PROJECT = "airflow_platform"  # the dev stack's compose project
DEFAULT_PORT = "8080"
PROJECT_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")  # docker compose project-name rule
COMPOSE = STACK / "compose.yaml"
OVERRIDE = STACK / "compose.projects.yaml"
ENV = STACK / ".env"
ENV_GENERATED = STACK / ".env.generated"
ENV_EXAMPLE = STACK / ".env.example"
REGISTRY = ROOT / "projects" / "projects.yaml"
WORKLOADS = ROOT / "workloads"
EXPECTED = ("postgres", "airflow-init", "airflow-apiserver", "airflow-scheduler",
            "airflow-dag-processor", "airflow-triggerer", "docker-proxy")
ONE_SHOT = ("airflow-init",)
GOOD = ("healthy", "ok")
TERMINAL = ("success", "failed")
DEFAULT_USER = "airflow"  # documented local default (stack/.env.example)


# ---------- pure helpers ----------

def generated_paths(project: str = PROJECT) -> tuple[Path, Path]:
    """(env file, compose override) that `render` writes for a compose project. The dev project keeps
    stack/.env.generated and stack/compose.projects.yaml; any other project (CI) gets its own pair under
    logs/<project>/ (git-ignored), so rendering another registry never changes the dev stack's files."""
    if project == PROJECT:
        return ENV_GENERATED, OVERRIDE
    folder = LOGS / project
    return folder / ".env.generated", folder / "compose.projects.yaml"


def compose_args(override_exists: bool, project: str = PROJECT) -> list[str]:
    """Base compose call. With the generated override, the generated env file comes too:
    compose reads every --env-file in order, a later file winning on duplicate names."""
    env_generated, override = generated_paths(project)
    args = ["docker", "compose", "-p", project, "-f", str(COMPOSE)]
    if override_exists:
        args += ["-f", str(override), "--env-file", str(ENV), "--env-file", str(env_generated)]
        return args
    return args + ["--env-file", str(ENV)]


def resolve_port(cli_port: int | None, env_text: str) -> str:
    """--port wins; else AIRFLOW_PORT from stack/.env (quotes stripped); else 8080."""
    if cli_port:
        return str(int(cli_port))
    return env_value(env_text, "AIRFLOW_PORT", DEFAULT_PORT).strip("\"'") or DEFAULT_PORT


def compose_env(port: str, base: dict | None = None) -> dict:
    """Process env for docker compose. AIRFLOW_PORT here beats the --env-file value (the shell env wins)."""
    env = dict(os.environ if base is None else base)
    env["AIRFLOW_PORT"] = str(port)
    return env


def log_name(base: str, project: str = PROJECT) -> str:
    """<base>.log for the dev project, <base>-<project>.log for any other."""
    return f"{base}.log" if project == PROJECT else f"{base}-{project}.log"


def compose_project(value: str) -> str:
    """argparse type for --compose-project."""
    if not PROJECT_NAME.match(value or ""):
        raise argparse.ArgumentTypeError(f"invalid compose project name {value!r} (lowercase letters, digits, _ and -)")
    return value


def override_yaml(override: dict) -> str:
    header = "# GENERATED from the projects registry by `python -m airflow_platform.stack render`; do not edit.\n"
    return header + yaml.safe_dump(override, sort_keys=False, default_flow_style=False, width=4096)


def active_dags(dags: list[dict]) -> dict[str, str]:
    """{dag_id: bundle_name} from GET /api/v2/dags entries, skipping stale (removed-bundle) DAGs."""
    return {d["dag_id"]: str(d.get("bundle_name") or "") for d in dags
            if d.get("dag_id") and not d.get("is_stale", False) and d.get("is_active", True)}


def active_dag_ids(dags: list[dict]) -> list[str]:
    return sorted(active_dags(dags))


def _ps_records(text: str) -> list[dict]:
    """`docker compose ps --format json` prints a JSON array (old) or one object per line (new)."""
    text = (text or "").strip()
    if not text:
        return []
    if text.startswith("["):
        return list(json.loads(text))
    return [json.loads(line) for line in text.splitlines() if line.strip().startswith("{")]


def service_health(rec: dict) -> str:
    """One word per service: docker's health if it has one, 'ok' for a one-shot that exited 0."""
    state = str(rec.get("State", "")).lower()
    health = str(rec.get("Health", "")).lower()
    service = rec.get("Service", "")
    if state == "exited":
        code = int(rec.get("ExitCode", -1) or 0)
        return "ok" if (code == 0 and service in ONE_SHOT) else f"exited({code})"
    if health:
        return health
    return state or "unknown"


def parse_ps(text: str) -> dict[str, str]:
    return {r["Service"]: service_health(r) for r in _ps_records(text) if r.get("Service")}


def container_names(text: str) -> list[str]:
    return [r["Name"] for r in _ps_records(text) if r.get("Name") and str(r.get("State", "")).lower() == "running"]


_UNITS = {"b": 1 / 2**20, "kib": 1 / 1024, "kb": 1 / 1024, "mib": 1, "mb": 1, "gib": 1024, "gb": 1024}


def parse_mem_mb(stats_text: str) -> int:
    """Sum the used memory column of `docker stats --no-stream --format {{.MemUsage}}` lines."""
    total = 0.0
    for line in (stats_text or "").splitlines():
        m = re.match(r"\s*([\d.]+)\s*([A-Za-z]+)", line.split("/")[0])
        if m:
            total += float(m.group(1)) * _UNITS.get(m.group(2).lower(), 0)
    return int(round(total))


def status_line(services: dict[str, str], airflow_version: str, url: str, mem_mb: int) -> dict:
    up = all(s in services for s in EXPECTED) and all(v in GOOD for v in services.values())
    return {"up": up, "services": services, "airflow_version": airflow_version, "url": url, "mem_mb": int(mem_mb)}


REQUIRED_COMPONENTS = ("metadatabase", "scheduler")


def remote_status_line(health: dict, airflow_version: str, url: str) -> dict:
    """Status of a stack seen only over HTTP (a tunnel), from GET /api/v2/monitor/health.
    Up when the metadatabase and the scheduler are healthy and no reported component is unhealthy."""
    services = {name: str((value or {}).get("status") or "unknown") for name, value in (health or {}).items()
                if isinstance(value, dict)}
    up = all(services.get(c) == "healthy" for c in REQUIRED_COMPONENTS) and \
        all(v == "healthy" for v in services.values())
    return {"up": up, "services": services, "airflow_version": airflow_version, "url": url, "mem_mb": 0,
            "remote": True}


def env_value(env_text: str, name: str, default: str) -> str:
    for line in env_text.splitlines():
        if line.strip().startswith(f"{name}="):
            return line.split("=", 1)[1].strip() or default
    return default


def workload_images(workloads_dir: Path) -> list[tuple[str, Path]]:
    """(tag, context) for every workloads/<name>/Dockerfile: airflow-platform/<name>:local."""
    if not workloads_dir.is_dir():
        return []
    return [(f"airflow-platform/{d.name}:local", d) for d in sorted(workloads_dir.iterdir())
            if (d / "Dockerfile").is_file()]


def trigger_payload(conf: dict | None = None) -> dict:
    """Body of POST /api/v2/dags/{dag_id}/dagRuns (3.x: logical_date may be null, the id is server-made)."""
    return {"logical_date": None, "conf": dict(conf or {})}


def run_result(dag_id: str, payload: dict) -> dict:
    """The one JSON line trigger/wait print, from a DAGRunResponse."""
    return {"dag_id": payload.get("dag_id", dag_id), "run_id": payload.get("dag_run_id", ""),
            "state": str(payload.get("state") or "unknown")}


def is_terminal(state: str) -> bool:
    return state in TERMINAL


def try_number(ti_payload: dict) -> int:
    """Latest try of a task instance (at least 1)."""
    return max(int(ti_payload.get("try_number") or 1), 1)


def log_lines(payload: dict) -> list[str]:
    """Text lines of a task-log response: content is a list of structured messages (3.x) or a string."""
    content = payload.get("content", "")
    if isinstance(content, str):
        return content.splitlines()
    lines = []
    for item in content or []:
        if isinstance(item, dict):
            text = str(item.get("event", ""))
            lines.extend(text.splitlines() or [""])
        else:
            lines.extend(str(item).splitlines())
    return lines


def count_import_errors(text: str) -> int:
    """`airflow dags list-import-errors -o json` prints a JSON list (or a 'no errors' message)."""
    data = None
    for start in ("[", "{"):
        i = (text or "").find(start)
        if i >= 0:
            try:
                data = json.loads(text[i:])
                break
            except json.JSONDecodeError:
                continue
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        return len(data.get("import_errors", []))
    return 0


# ---------- side effects ----------

class Target:
    """The stack this process talks to: compose project and host port. Set once in main()."""
    project: str = PROJECT
    port: int | None = None  # None: AIRFLOW_PORT from stack/.env, else 8080


def _port() -> str:
    return resolve_port(Target.port, ENV.read_text(encoding="utf-8") if ENV.exists() else "")


def _run(args: list[str], timeout: float = 120) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, env=compose_env(_port()))
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, -9, "", f"timeout after {timeout}s")
    except OSError as exc:
        return subprocess.CompletedProcess(args, -1, "", f"{type(exc).__name__}: {exc}")


def _logged(args: list[str], log_name: str, timeout: float) -> tuple[int, str]:
    """Run a long docker command with its output in logs/<log_name>; return (code, last lines)."""
    LOGS.mkdir(exist_ok=True)
    log = LOGS / log_name
    r = _run(args, timeout=timeout)
    log.write_text((r.stdout or "") + (r.stderr or ""), encoding="utf-8")
    tail = " | ".join(((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-3:])[:300]
    return r.returncode, tail


def ensure_env() -> bool:
    if not ENV.exists():
        shutil.copyfile(ENV_EXAMPLE, ENV)
        return True
    return False


def _compose() -> list[str]:
    env_generated, override = generated_paths(Target.project)
    return compose_args(override.exists() and env_generated.exists(), Target.project)


def build_workloads(timeout: float) -> tuple[bool, list[str], str]:
    """docker build every workloads/<name> image; output in logs/workload-<name>.log."""
    built = []
    for tag, ctx in workload_images(WORKLOADS):
        code, tail = _logged(["docker", "build", "-t", tag, str(ctx)], f"workload-{ctx.name}.log", timeout)
        if code != 0:
            return False, built, f"{tag}: {tail}"
        built.append(tag)
    return True, built, ""


def render(projects_file: str | Path, target: str = "local") -> dict:
    """Write stack/.env.generated and stack/compose.projects.yaml from a projects registry."""
    path = Path(projects_file).resolve()
    projects = registry.load(path)
    env_generated, override = generated_paths(Target.project)
    env_generated.parent.mkdir(parents=True, exist_ok=True)
    env_generated.write_text(registry.render_env(projects, target), encoding="utf-8", newline="\n")
    override.write_text(override_yaml(registry.render_compose_override(projects, path.parent, path.name)),
                        encoding="utf-8", newline="\n")
    return {"command": "render", "ok": True, "projects": [p.name for p in projects], "target": target,
            "compose_project": Target.project,
            "files": [f.relative_to(ROOT).as_posix() for f in (env_generated, override)]}


def cmd_render(args) -> dict:
    return render(args.projects, args.target)


def cmd_up(args) -> dict:
    created = ensure_env()
    rendered = render(args.projects)
    ok, built, err = build_workloads(timeout=args.timeout)
    if not ok:
        return {"command": "up", "ok": False, "env_created": created, "workloads": built, "tail": err}
    log = log_name("stack-up", Target.project)
    code, tail = _logged(_compose() + ["up", "-d", "--build", "--wait"], log, timeout=args.timeout)
    return {"command": "up", "ok": code == 0, "env_created": created, "projects": rendered["projects"],
            "compose_project": Target.project, "url": f"http://localhost:{_port()}",
            "workloads": built, "log": f"logs/{log}", **({} if code == 0 else {"tail": tail})}


def cmd_down(args) -> dict:
    ensure_env()
    extra = ["--volumes"] if args.volumes else []
    code, tail = _logged(_compose() + ["down", *extra], log_name("stack-down", Target.project), timeout=300)
    return {"command": "down", "ok": code == 0, "compose_project": Target.project,
            "volumes_removed": bool(args.volumes), **({} if code == 0 else {"tail": tail})}


def cmd_compose_logs(args) -> dict:
    """`docker compose logs` of every service into logs/compose-<project>.log (the CI failure artifact)."""
    ensure_env()
    LOGS.mkdir(exist_ok=True)
    log = LOGS / f"compose-{Target.project}.log"
    r = _run(_compose() + ["logs", "--no-color", "--timestamps"], timeout=300)
    log.write_text((r.stdout or "") + (r.stderr or ""), encoding="utf-8")
    return {"command": "compose-logs", "ok": r.returncode == 0, "compose_project": Target.project,
            "log": log.relative_to(ROOT).as_posix()}


def airflow_version() -> str:
    r = _run(_compose() + ["exec", "-T", "airflow-scheduler", "airflow", "version"], timeout=90)
    lines = [l.strip() for l in (r.stdout or "").splitlines() if re.match(r"^\d+\.\d+\.\d+", l.strip())]
    return lines[-1] if r.returncode == 0 and lines else ""


def mem_mb(names: list[str]) -> int:
    if not names:
        return 0
    r = _run(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", *names], timeout=90)
    return parse_mem_mb(r.stdout) if r.returncode == 0 else 0


def import_errors() -> int:
    """Number of DAG import errors (-1 when the CLI could not be asked)."""
    r = _run(_compose() + ["exec", "-T", "airflow-scheduler", "airflow", "dags", "list-import-errors",
                           "-o", "json"], timeout=120)
    return count_import_errors(r.stdout) if r.returncode == 0 else -1


def remote_status(url: str, dags: bool) -> dict:
    """`status --url`: a stack reached through a tunnel, so no docker calls; health route is public."""
    base = base_url(url)
    try:
        health = _http("GET", f"{base}/api/v2/monitor/health", timeout=15)
    except (RuntimeError, OSError, ValueError) as exc:
        return {"up": False, "services": {}, "airflow_version": "", "url": base, "mem_mb": 0, "remote": True,
                "error": f"{type(exc).__name__}: {exc}"[:200]}
    version, api = "", None
    try:
        api = Api(base)
        version = str(api.call("GET", "/version").get("version") or "")
    except (RuntimeError, OSError, ValueError, KeyError):
        pass
    line = remote_status_line(health, version, base)
    if dags:
        try:
            found = list_dags(base)
        except (RuntimeError, OSError, ValueError, KeyError) as exc:
            found = {}
            line["dags_error"] = f"{type(exc).__name__}: {exc}"[:200]
        line["dag_ids"] = sorted(found)
        line["dag_bundles"] = dict(sorted(found.items()))
    return line


def cmd_status(args) -> dict:
    if getattr(args, "url", None):
        return remote_status(args.url, args.dags)
    ensure_env()
    port = _port()
    ps = _run(_compose() + ["ps", "-a", "--format", "json"], timeout=60)
    services = parse_ps(ps.stdout) if ps.returncode == 0 else {}
    running = any(v != "ok" and not v.startswith("exited") for v in services.values())
    version = airflow_version() if running else ""
    line = status_line(services, version, f"http://localhost:{port}", mem_mb(container_names(ps.stdout)))
    line["compose_project"] = Target.project
    line["import_errors"] = import_errors() if services.get("airflow-scheduler") in GOOD else -1
    line["projects"] = [p.name for p in registry.load(args.projects)]
    if args.dags:
        found: dict[str, str] = {}
        if services.get("airflow-apiserver") in GOOD:
            try:
                found = list_dags()
            except (RuntimeError, OSError, ValueError, KeyError) as exc:
                line["dags_error"] = f"{type(exc).__name__}: {exc}"[:200]
        line["dag_ids"] = sorted(found)
        line["dag_bundles"] = dict(sorted(found.items()))
    return line


def list_dags(url: str | None = None) -> dict[str, str]:
    """Active {dag_id: bundle_name} from GET /api/v2/dags, paged."""
    api, found, offset, limit = Api(url), {}, 0, 100
    while True:
        page = api.call("GET", f"/dags?limit={limit}&offset={offset}")
        dags = page.get("dags", [])
        found.update(active_dags(dags))
        offset += len(dags)
        if not dags or offset >= int(page.get("total_entries", 0)):
            return found


# ---------- REST API v2 (token from the FAB auth manager's POST /auth/token) ----------

def base_url(url: str | None = None) -> str:
    if url:
        return url.rstrip("/")
    return f"http://localhost:{_port()}"


def _credentials() -> tuple[str, str]:
    env_text = ENV.read_text(encoding="utf-8") if ENV.exists() else ""
    return (env_value(env_text, "_AIRFLOW_WWW_USER_USERNAME", DEFAULT_USER),
            env_value(env_text, "_AIRFLOW_WWW_USER_PASSWORD", DEFAULT_USER))


def _http(method: str, url: str, body: dict | None = None, token: str | None = None,
          timeout: float = 30) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        raise RuntimeError(f"{method} {urllib.parse.urlsplit(url).path} -> {exc.code}: {detail}") from None
    return json.loads(raw) if raw.strip() else {}


class Api:
    """Tiny REST API v2 client. The token lives only in this object."""

    def __init__(self, url: str | None = None):
        self.url = base_url(url)
        user, password = _credentials()
        self._token = _http("POST", f"{self.url}/auth/token", {"username": user, "password": password})["access_token"]

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        return _http(method, f"{self.url}/api/v2{path}", body, self._token)


def _q(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def cmd_trigger(args) -> dict:
    conf = json.loads(args.conf) if args.conf else {}
    api = Api(args.url)
    dag = _q(args.dag_id)
    api.call("PATCH", f"/dags/{dag}", {"is_paused": False})  # DAGs are paused at creation
    return run_result(args.dag_id, api.call("POST", f"/dags/{dag}/dagRuns", trigger_payload(conf)))


def cmd_wait(args) -> dict:
    api = Api(args.url)
    path = f"/dags/{_q(args.dag_id)}/dagRuns/{_q(args.run_id)}"
    deadline = time.monotonic() + args.timeout
    while True:
        result = run_result(args.dag_id, api.call("GET", path))
        if is_terminal(result["state"]) or time.monotonic() >= deadline:
            return {**result, "timed_out": not is_terminal(result["state"])}
        time.sleep(3)


def cmd_logs(args) -> dict:
    api = Api(args.url)
    ti_path = f"/dags/{_q(args.dag_id)}/dagRuns/{_q(args.run_id)}/taskInstances/{_q(args.task_id)}"
    ti = api.call("GET", ti_path)
    tries = try_number(ti)
    lines = log_lines(api.call("GET", f"{ti_path}/logs/{tries}?full_content=true"))
    for line in lines[-20:]:
        print(line)
    return {"dag_id": args.dag_id, "run_id": args.run_id, "task_id": args.task_id,
            "state": str(ti.get("state") or "unknown"), "try_number": tries, "lines": len(lines)}


def links_result(payload: dict) -> dict:
    """The one JSON line `links` prints, from GET .../taskInstances/{task_id}/links (ExtraLinkCollectionResponse)."""
    return {"links": dict(payload.get("extra_links") or {}), "source": "api"}


def cmd_plugins(args) -> dict:
    """GET /api/v2/plugins, paged; the whole PluginCollectionResponse as one line."""
    api, plugins, offset = Api(args.url), [], 0
    while True:
        page = api.call("GET", f"/plugins?limit=100&offset={offset}")
        plugins += page.get("plugins", [])
        offset = len(plugins)
        if not page.get("plugins") or offset >= int(page.get("total_entries", 0)):
            return {"plugins": plugins, "total_entries": len(plugins)}


def cmd_links(args) -> dict:
    path = f"/dags/{_q(args.dag_id)}/dagRuns/{_q(args.run_id)}/taskInstances/{_q(args.task_id)}/links"
    return links_result(Api(args.url).call("GET", path))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m airflow_platform.stack")
    sub = p.add_subparsers(dest="command", required=True)
    up = sub.add_parser("up", help="build the image and start the stack, waiting for health")
    up.add_argument("--timeout", type=float, default=1800)
    down = sub.add_parser("down", help="stop the stack (volumes are kept unless --volumes)")
    down.add_argument("--volumes", action="store_true")
    status = sub.add_parser("status", help="print one JSON status line")
    status.add_argument("--dags", action="store_true", help="add the active DAG ids from the REST API")
    rend = sub.add_parser("render", help="write stack/.env.generated and stack/compose.projects.yaml")
    rend.add_argument("--target", choices=("local", "cloud"), default="local")
    for sp in (up, status, rend):
        sp.add_argument("--projects", default=str(REGISTRY), help="projects registry (default projects/projects.yaml)")
    trig = sub.add_parser("trigger", help="unpause and trigger a DAG run over the REST API")
    trig.add_argument("dag_id")
    trig.add_argument("--conf", default=None, help="JSON object passed as the run conf")
    wait = sub.add_parser("wait", help="poll a DAG run until it succeeds or fails")
    wait.add_argument("dag_id")
    wait.add_argument("run_id")
    wait.add_argument("--timeout", type=float, default=300)
    logs = sub.add_parser("logs", help="print the last 20 lines of a task log")
    logs.add_argument("dag_id")
    logs.add_argument("run_id")
    logs.add_argument("task_id")
    plug = sub.add_parser("plugins", help="print GET /api/v2/plugins as one JSON line")
    links = sub.add_parser("links", help="print a task instance's extra links from the REST API")
    links.add_argument("dag_id")
    links.add_argument("run_id")
    links.add_argument("task_id")
    for sp in (trig, wait, logs, plug, links):
        sp.add_argument("--url", default=None, help="Airflow base URL (default http://localhost:<port>)")
    status.add_argument("--url", default=None,
                        help="check a stack over HTTP only (e.g. a tunnel to a VM): /api/v2/monitor/health, no docker")
    clogs = sub.add_parser("compose-logs", help="write `docker compose logs` to logs/compose-<project>.log")
    for sp in (up, down, status, rend, trig, wait, logs, plug, links, clogs):
        sp.add_argument("--compose-project", type=compose_project, default=PROJECT,
                        help=f"docker compose project (default {PROJECT}, the dev stack)")
        sp.add_argument("--port", type=int, default=None,
                        help=f"host UI / REST API port (default AIRFLOW_PORT from stack/.env, else {DEFAULT_PORT})")
    args = p.parse_args(argv)
    Target.project, Target.port = args.compose_project, args.port
    commands = {"up": cmd_up, "down": cmd_down, "status": cmd_status, "render": cmd_render,
                "trigger": cmd_trigger, "wait": cmd_wait, "logs": cmd_logs, "plugins": cmd_plugins,
                "links": cmd_links, "compose-logs": cmd_compose_logs}
    try:
        result = commands[args.command](args)
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        result = {"command": args.command, "ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
        if args.command in ("trigger", "wait", "logs"):
            result = {"dag_id": args.dag_id, "run_id": getattr(args, "run_id", ""), "state": "error",
                      "error": result["error"]}
    print(json.dumps(result))
    if args.command == "status":
        return 0 if result.get("up") else 1
    if args.command in ("trigger", "logs"):
        return 0 if result.get("state") not in ("error",) else 1
    if args.command == "wait":
        return 0 if result.get("state") == "success" else 1
    if args.command in ("plugins", "links"):
        return 1 if result.get("ok") is False else 0
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
