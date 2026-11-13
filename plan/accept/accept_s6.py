"""S6 acceptance: CI workflow shape + the CI stack sequence passes locally."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import check, finish, guarded, no_secrets, pwsh, pytest_check, read, tail  # noqa: E402


def static():
    wf = read(".github/workflows/ci.yml")
    check("workflow exists", bool(wf))
    check("python and stack jobs", re.search(r"^\s{2}python:", wf, re.M) and re.search(r"^\s{2}stack:", wf, re.M))
    check("no secrets referenced", "secrets." not in wf)
    uses = re.findall(r"uses:\s*(\S+)", wf)
    check("actions pinned", uses and all(re.search(r"@(v\d+|[0-9a-f]{40})", u) for u in uses), ",".join(uses))
    check("ci registry has only examples", "name: examples" in read("projects/ci.yaml") and "governor" not in read("projects/ci.yaml"))
    no_secrets()


def local_ci():
    r = pwsh("scripts/ci-local.ps1", timeout=1500)
    check("ci-local.ps1 passes", r.returncode == 0, tail(r))


guarded(static)
guarded(local_ci)
guarded(pytest_check, "tests", ["test_ci_workflow_has_jobs_python_and_stack", "test_ci_has_no_secrets_reference",
                                "test_actions_are_pinned", "test_ci_registry_has_only_examples"])
finish("S6")
