"""S3 acceptance: projects.yaml renders bundles; a new project loads without code changes."""
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT, check, finish, guarded, no_secrets, pytest_check, read, stack, tail, trigger_and_wait  # noqa: E402

TMP = ROOT / "logs" / "tmp_project"
REG = ROOT / "logs" / "tmp_projects.yaml"
DAG = '''from airflow.sdk import DAG
from airflow.providers.standard.operators.empty import EmptyOperator
import pendulum
with DAG(dag_id="tmp_project_probe", schedule=None, start_date=pendulum.datetime(2026, 1, 1), catchup=False):
    EmptyOperator(task_id="noop")
'''


def static():
    gi = read(".gitignore")
    check("generated files ignored", "stack/.env.generated" in gi and "stack/compose.projects.yaml" in gi)
    c = read("stack/compose.yaml")
    check("S2 temporary dags mount removed", "dags/examples" not in c)
    no_secrets()


def dag_ids(projects_file: str, want: str | None = None, wait_s: int = 180) -> set:
    """Active DAG ids; when `want` is given, poll until it appears or wait_s passes (the DAG processor parses async)."""
    deadline = time.time() + wait_s
    while True:
        s, r = stack("status", "--projects", projects_file, "--dags", timeout=120)
        ids = set((s or {}).get("dag_ids") or [])
        if s is None or want is None or want in ids or time.time() > deadline:
            return ids
        time.sleep(10)


def live():
    _, r = stack("up", timeout=900)
    if not check("stack up with bundles", r.returncode == 0, tail(r)):
        return
    trigger_and_wait("hello_workload")
    TMP.mkdir(parents=True, exist_ok=True)
    (TMP / "probe.py").write_text(DAG, encoding="utf-8")
    base = read("projects/projects.yaml").replace("../dags/examples", str((ROOT / "dags/examples").as_posix()))
    REG.write_text(base.rstrip() + f"\n  - name: tmp-project\n    dags: {{local: {TMP.as_posix()}}}\n", encoding="utf-8")
    try:
        _, r = stack("up", "--projects", str(REG), timeout=900)
        check("up with a third project", r.returncode == 0, tail(r))
        check("new project's DAG loaded", "tmp_project_probe" in dag_ids(str(REG), want="tmp_project_probe"), "")
    finally:
        _, r = stack("up", timeout=900)
        check("back to the real registry", r.returncode == 0, tail(r))
        shutil.rmtree(TMP, ignore_errors=True)
        REG.unlink(missing_ok=True)
    check("registry file untouched by the test", "tmp-project" not in read("projects/projects.yaml"))


guarded(static)
guarded(live)
guarded(pytest_check, "tests", ["test_render_local_bundle_per_project", "test_render_cloud_uses_git_bundle_and_skips_local_only",
                                "test_override_mounts_are_read_only", "test_override_paths_use_forward_slashes",
                                "test_adding_a_project_changes_only_generated_output"])
finish("S3")
