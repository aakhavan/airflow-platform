"""S0 acceptance: scaffold, tooling, projects loader."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import check, exists, finish, guarded, no_secrets, pytest_check, read  # noqa: E402


def static():
    py = read("pyproject.toml")
    check("pyproject exists", bool(py))
    check("no apache-airflow in pyproject", "apache-airflow" not in py.lower())
    check("pyyaml dependency", "pyyaml" in py.lower())
    gi = read(".gitignore")
    for pat in [".env", "!.env.example", "stack/.env.generated", "stack/compose.projects.yaml", "logs/", ".terraform/", ".factory/"]:
        check(f".gitignore has {pat}", pat in gi)
    check(".tfstate ignored", "tfstate" in gi)
    check(".gitattributes eol=lf", "eol=lf" in read(".gitattributes"))
    check("projects.yaml exists", exists("projects/projects.yaml"))
    check("CONTEXT.md and 3 ADRs present", exists("CONTEXT.md") and len(list(Path(__file__).resolve().parents[2].glob("docs/adr/000*.md"))) >= 3)
    no_secrets()


guarded(static)
guarded(pytest_check, "tests", ["test_load_valid_registry", "test_duplicate_names_rejected", "test_unknown_placeholder_rejected",
                                "test_missing_local_path_names_project", "test_task_link_needs_prefix"])
finish("S0")
