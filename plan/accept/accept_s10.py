"""S10 acceptance: README and docs complete, links resolve, diagrams present."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT, check, finish, guarded, no_secrets, read  # noqa: E402

SECTIONS = ["quick start", "add a project", "targets", "cost", "limits", "repo map"]


def docs():
    rd = read("README.md")
    low = rd.lower()
    for s in SECTIONS:
        check(f"README section: {s}", re.search(rf"^#+ .*{s}", low, re.M) is not None)
    check("README has no TODO", "todo" not in low)
    check("Kubernetes named as future target", "kubernetes" in low)
    arch = read("docs/architecture.md")
    blocks = re.findall(r"```mermaid\n(.*?)```", arch, re.S)
    check("two mermaid diagrams", len(blocks) >= 2, str(len(blocks)))
    check("mermaid blocks start with a diagram type", all(b.strip().split()[0] in ("flowchart", "graph", "sequenceDiagram") for b in blocks))
    check("learning page exists", len(read("docs/learning/airflow-platform.md")) > 3000)
    check("LICENSE is MIT", "MIT" in read("LICENSE"))
    broken = []
    for f in [ROOT / "README.md", *ROOT.joinpath("docs").rglob("*.md")]:
        for link in re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", f.read_text(encoding="utf-8")):
            if "://" in link or link.startswith("mailto:"):
                continue
            if not (f.parent / link).resolve().exists():
                broken.append(f"{f.name}->{link}")
    check("relative links resolve", not broken, "; ".join(broken[:4]))
    no_secrets()


guarded(docs)
finish("S10")
