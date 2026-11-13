"""Shared helpers for airflow-platform acceptance scripts (factory PLAN.md §4 contract).

Stdlib only at import time, so every script fails cleanly (JSON last line) on an empty repo.
Run as: uv run python plan/accept/accept_sN.py
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_checks: list[dict] = []
# pandas is NOT listed: the official base image ships it as a hard dependency of the google provider (Airflow's own
# constraints), not as project code. The rule is about project libraries.
DENYLIST = ["dbt-core", "langchain", "langgraph", "governor", "streamlit"]
ALLOWED_DAG_IMPORTS = ("airflow", "datetime", "pendulum", "json", "os", "pathlib", "typing", "docker", "__future__")


def check(name: str, ok: bool, detail: str = "") -> bool:
    _checks.append({"name": name, "ok": bool(ok), "detail": str(detail)[:240]})
    return bool(ok)


def finish(step: str) -> None:
    ok = all(c["ok"] for c in _checks) and bool(_checks)
    for c in _checks:
        if not c["ok"]:
            print(f"FAIL {c['name']}: {c['detail']}"[:200])
    print(json.dumps({"step": step, "pass": ok, "checks": _checks}))
    sys.exit(0 if ok else 1)


def guarded(fn, *args, **kwargs):
    """Run one check group; an exception becomes a failed check instead of a crash."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        check(f"{fn.__name__} ran", False, f"{type(exc).__name__}: {exc}")
        return None


def run(args: list[str], timeout: float = 600, env: dict | None = None, cwd: Path | None = None):
    try:
        return subprocess.run(args, cwd=cwd or ROOT, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, -9, "", f"timeout after {timeout}s")
    except OSError as exc:
        return subprocess.CompletedProcess(args, -1, "", f"{type(exc).__name__}: {exc}")


def last_json(text: str):
    for line in reversed((text or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{") or line.startswith("["):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None


def tail(r) -> str:
    lines = (r.stdout or "").strip().splitlines() + (r.stderr or "").strip().splitlines()
    return " | ".join(lines[-3:])[:240]


def stack(*args: str, timeout: float = 900):
    """python -m airflow_platform.stack <args>; returns (json | None, CompletedProcess)."""
    r = run([sys.executable, "-m", "airflow_platform.stack", *args], timeout=timeout)
    return last_json(r.stdout), r


def pwsh(script: str, *args: str, timeout: float = 900, env: dict | None = None):
    exe = shutil.which("pwsh") or shutil.which("powershell")
    if not exe:
        return subprocess.CompletedProcess([script], -1, "", "pwsh not found")
    return run([exe, "-NoProfile", "-File", str(ROOT / script), *args], timeout=timeout, env=env)


def pytest_check(target: str = "tests", required: list[str] | None = None) -> None:
    r = run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", target], timeout=900)
    summary = next((l for l in reversed(r.stdout.strip().splitlines()) if "passed" in l or "failed" in l
                    or "error" in l or "no tests" in l), tail(r))
    check(f"pytest {target}", r.returncode == 0, summary)
    if required:
        c = run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", target], timeout=300)
        names = set(re.findall(r"::(test_[A-Za-z0-9_]+)", c.stdout))
        missing = [t for t in required if t not in names]
        check("required tests present", not missing, f"missing: {missing}" if missing else f"{len(required)} found")


def http_status(url: str, timeout: float = 15) -> int:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:  # noqa: BLE001
        return -1


def read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


def exists(rel: str) -> bool:
    return (ROOT / rel).exists()


def grep(paths: list[str], pattern: str, exclude: tuple[str, ...] = (".env.example",)) -> list[str]:
    rx = re.compile(pattern)
    hits = []
    for rel in paths:
        base = ROOT / rel
        files = [base] if base.is_file() else (list(base.rglob("*")) if base.is_dir() else [])
        for f in files:
            if not f.is_file() or f.name in exclude or ".terraform" in f.parts or f.suffix in {".png", ".lock"}:
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
            if rx.search(text):
                hits.append(str(f.relative_to(ROOT)))
    return hits


def no_secrets() -> None:
    pat = (r"(AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY|sk-[A-Za-z0-9]{20,}|"
           r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}|\"private_key\":)")
    hits = grep(["src", "stack", "image", "plugins", "dags", "workloads", "scripts", "terraform", "docs",
                 "projects", "tests", ".github", "README.md"], pat)
    check("no secrets in repo files", not hits, "; ".join(hits[:3]))


def dag_imports_ok(folder: Path) -> tuple[bool, str]:
    bad = []
    for f in folder.rglob("*.py") if folder.is_dir() else []:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            for m in mods:
                if not m.split(".")[0] in ALLOWED_DAG_IMPORTS:
                    bad.append(f"{f.name}:{m}")
    return (not bad), ", ".join(bad[:5])


def trigger_and_wait(dag_id: str, timeout: int = 420, url: str | None = None) -> dict:
    extra = ["--url", url] if url else []
    t, r = stack("trigger", dag_id, *extra, timeout=120)
    if not check(f"trigger {dag_id}", bool(t and t.get("run_id")), tail(r) if not t else t.get("run_id", "")):
        return {}
    w, r = stack("wait", dag_id, t["run_id"], "--timeout", str(timeout), *extra, timeout=timeout + 60)
    check(f"{dag_id} run succeeded", bool(w) and w.get("state") == "success", str(w or tail(r))[:200])
    return {"run_id": t["run_id"], **(w or {})}


def docker(*args: str, timeout: float = 300):
    return run(["docker", *args], timeout=timeout)


def env_without(names: tuple[str, ...]) -> dict:
    env = dict(os.environ)
    for n in names:
        env.pop(n, None)
    return env
