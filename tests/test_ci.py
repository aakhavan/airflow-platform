"""Offline tests for the CI workflow (S6, docs/spec.md §11) and the stack module's second-stack options."""
import re
from pathlib import Path

import pytest
import yaml

from airflow_platform import projects, stack

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def _wf() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _on(wf: dict) -> dict:
    # PyYAML (YAML 1.1) reads the bare key `on` as the boolean True.
    return wf.get("on", wf.get(True))


def test_ci_workflow_has_jobs_python_and_stack():
    wf = _wf()
    assert set(_on(wf)) >= {"push", "pull_request"}
    assert wf["permissions"] == {"contents": "read"}
    jobs = wf["jobs"]
    assert {"python", "stack"} <= set(jobs)
    for job in jobs.values():
        assert job["runs-on"] == "ubuntu-latest"

    py = " ".join(s.get("run", "") + s.get("uses", "") for s in jobs["python"]["steps"])
    assert "astral-sh/setup-uv@" in py and "uv sync --frozen" in py and "uv run pytest -q" in py

    steps = jobs["stack"]["steps"]
    runs = [s.get("run", "") for s in steps]
    text = "\n".join(runs)
    assert "scripts/up.ps1 -Projects projects/ci.yaml" in text
    assert "import_errors" in text and "trigger hello_workload" in text
    assert re.search(r"wait hello_workload .*--timeout 300", text)
    down = [s for s in steps if "down.ps1 -Volumes" in s.get("run", "")]
    assert len(down) == 1 and down[0]["if"] == "always()" and steps[-1] is down[0]
    upload = [s for s in steps if s.get("uses", "").startswith("actions/upload-artifact@")]
    assert len(upload) == 1 and upload[0]["if"] == "failure()"
    logs = [s for s in steps if "compose-logs" in s.get("run", "")]
    assert logs and steps.index(logs[0]) < steps.index(upload[0]) < steps.index(down[0])


def test_ci_has_no_secrets_reference():
    assert "secrets." not in WORKFLOW.read_text(encoding="utf-8")


def test_actions_are_pinned():
    uses = re.findall(r"uses:\s*(\S+)", WORKFLOW.read_text(encoding="utf-8"))
    assert uses
    for u in uses:
        assert re.search(r"@(v\d+|[0-9a-f]{40})$", u), u


def test_ci_registry_has_only_examples():
    path = ROOT / "projects" / "ci.yaml"
    assert "governor" not in path.read_text(encoding="utf-8")
    loaded = projects.load(path)  # every path in it exists in a plain checkout
    assert [p.name for p in loaded] == ["examples"]
    assert loaded[0].dags.local == (ROOT / "dags" / "examples").resolve()


# --- the second stack (scripts/ci-local.ps1) --------------------------------------------------

def test_dev_project_keeps_its_generated_files():
    assert stack.generated_paths() == (stack.ENV_GENERATED, stack.OVERRIDE)
    assert stack.compose_args(True)[:4] == ["docker", "compose", "-p", "airflow_platform"]


def test_other_project_gets_its_own_generated_files():
    env, override = stack.generated_paths("airflow_platform_ci")
    assert env.parent == override.parent == stack.LOGS / "airflow_platform_ci"
    args = stack.compose_args(True, "airflow_platform_ci")
    assert args[:4] == ["docker", "compose", "-p", "airflow_platform_ci"]
    assert str(override) in args and str(env) in args
    assert str(stack.OVERRIDE) not in args and str(stack.ENV_GENERATED) not in args


def test_resolve_port():
    assert stack.resolve_port(8081, "AIRFLOW_PORT=8080\n") == "8081"
    assert stack.resolve_port(None, "AIRFLOW_PORT=9090\n") == "9090"
    assert stack.resolve_port(None, 'AIRFLOW_PORT="9091"\n') == "9091"
    assert stack.resolve_port(None, "") == "8080"


def test_compose_env_sets_port_without_touching_base():
    base = {"PATH": "x", "AIRFLOW_PORT": "8080"}
    env = stack.compose_env("8081", base)
    assert env["AIRFLOW_PORT"] == "8081" and env["PATH"] == "x" and base["AIRFLOW_PORT"] == "8080"


def test_log_names_do_not_collide():
    assert stack.log_name("stack-up") == "stack-up.log"
    assert stack.log_name("stack-up", "airflow_platform_ci") == "stack-up-airflow_platform_ci.log"


@pytest.mark.parametrize("argv", [
    ["up"], ["down"], ["status"], ["render"], ["trigger", "d"], ["wait", "d", "r"],
    ["logs", "d", "r", "t"], ["plugins"], ["links", "d", "r", "t"], ["compose-logs"],
])
def test_every_subcommand_takes_compose_project_and_port(argv, monkeypatch, capsys):
    seen = {}

    def fake(args):
        seen.update(project=stack.Target.project, port=stack.Target.port)
        return {"ok": True, "up": True, "state": "success"}

    command = argv[0]
    monkeypatch.setattr(stack, {"compose-logs": "cmd_compose_logs"}.get(command, f"cmd_{command}"), fake)
    monkeypatch.setattr(stack.Target, "project", stack.PROJECT)
    monkeypatch.setattr(stack.Target, "port", None)
    assert stack.main(argv + ["--compose-project", "airflow_platform_ci", "--port", "8081"]) == 0
    assert seen == {"project": "airflow_platform_ci", "port": 8081}


def test_bad_compose_project_rejected():
    with pytest.raises(SystemExit):
        stack.main(["status", "--compose-project", "Bad Name"])


def test_wait_exit_code_is_nonzero_unless_success(monkeypatch, capsys):
    for state, code in (("success", 0), ("failed", 1), ("running", 1), ("queued", 1)):
        monkeypatch.setattr(stack, "cmd_wait", lambda args, s=state: {"dag_id": "d", "run_id": "r", "state": s})
        assert stack.main(["wait", "d", "r"]) == code, state


def test_ci_local_isolated_from_dev_stack():
    text = (ROOT / "scripts" / "ci-local.ps1").read_text(encoding="utf-8")
    assert "'airflow_platform_ci'" in text and "8081" in text and "projects/ci.yaml" in text
    assert "down.ps1') -Volumes -ComposeProject $ComposeProject" in text
