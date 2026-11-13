"""Local stack control: python -m airflow_platform.stack up|down|status.

Every command prints one JSON line last. Docker output goes to logs/ (git-ignored).
The parsing helpers (parse_ps, parse_mem_mb, status_line) are pure and tested offline.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STACK = ROOT / "stack"
LOGS = ROOT / "logs"
PROJECT = "airflow_platform"
COMPOSE = STACK / "compose.yaml"
OVERRIDE = STACK / "compose.projects.yaml"
ENV = STACK / ".env"
ENV_EXAMPLE = STACK / ".env.example"
EXPECTED = ("postgres", "airflow-init", "airflow-apiserver", "airflow-scheduler",
            "airflow-dag-processor", "airflow-triggerer")
ONE_SHOT = ("airflow-init",)
GOOD = ("healthy", "ok")


# ---------- pure helpers ----------

def compose_args(override_exists: bool) -> list[str]:
    args = ["docker", "compose", "-p", PROJECT, "-f", str(COMPOSE)]
    if override_exists:
        args += ["-f", str(OVERRIDE)]
    return args + ["--env-file", str(ENV)]


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


def env_value(env_text: str, name: str, default: str) -> str:
    for line in env_text.splitlines():
        if line.strip().startswith(f"{name}="):
            return line.split("=", 1)[1].strip() or default
    return default


# ---------- side effects ----------

def _run(args: list[str], timeout: float = 120) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout)
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
    return compose_args(OVERRIDE.exists())


def cmd_up(args) -> dict:
    created = ensure_env()
    code, tail = _logged(_compose() + ["up", "-d", "--build", "--wait"], "stack-up.log", timeout=args.timeout)
    return {"command": "up", "ok": code == 0, "env_created": created, "log": "logs/stack-up.log",
            **({} if code == 0 else {"tail": tail})}


def cmd_down(args) -> dict:
    ensure_env()
    extra = ["--volumes"] if args.volumes else []
    code, tail = _logged(_compose() + ["down", *extra], "stack-down.log", timeout=300)
    return {"command": "down", "ok": code == 0, "volumes_removed": bool(args.volumes),
            **({} if code == 0 else {"tail": tail})}


def airflow_version() -> str:
    r = _run(_compose() + ["exec", "-T", "airflow-scheduler", "airflow", "version"], timeout=90)
    lines = [l.strip() for l in (r.stdout or "").splitlines() if re.match(r"^\d+\.\d+\.\d+", l.strip())]
    return lines[-1] if r.returncode == 0 and lines else ""


def mem_mb(names: list[str]) -> int:
    if not names:
        return 0
    r = _run(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", *names], timeout=90)
    return parse_mem_mb(r.stdout) if r.returncode == 0 else 0


def cmd_status(args) -> dict:
    ensure_env()
    port = env_value(ENV.read_text(encoding="utf-8"), "AIRFLOW_PORT", "8080")
    ps = _run(_compose() + ["ps", "-a", "--format", "json"], timeout=60)
    services = parse_ps(ps.stdout) if ps.returncode == 0 else {}
    running = any(v != "ok" and not v.startswith("exited") for v in services.values())
    version = airflow_version() if running else ""
    return status_line(services, version, f"http://localhost:{port}", mem_mb(container_names(ps.stdout)))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m airflow_platform.stack")
    sub = p.add_subparsers(dest="command", required=True)
    up = sub.add_parser("up", help="build the image and start the stack, waiting for health")
    up.add_argument("--timeout", type=float, default=1800)
    down = sub.add_parser("down", help="stop the stack (volumes are kept unless --volumes)")
    down.add_argument("--volumes", action="store_true")
    sub.add_parser("status", help="print one JSON status line")
    args = p.parse_args(argv)
    result = {"up": cmd_up, "down": cmd_down, "status": cmd_status}[args.command](args)
    print(json.dumps(result))
    if args.command == "status":
        return 0 if result["up"] else 1
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
