# NOTES

## Current state
S0 scaffold is in place and accept_s0 passed (7 tests). The host project is uv on Python 3.12 with pyyaml 6.0.3 and pytest 9.2.0. projects/projects.yaml registers only examples, with DAG files under dags/examples/ (directory present, no DAG yet). load and validate check unique names matching [a-z0-9-]+, an existing dags.local relative to the YAML file, task-link placeholders limited to run_id, dag_id, and task_id, and a non-empty dag_prefix when a task link is set. Bundle and compose rendering are stubs for S3. Next step is S1, the Airflow image and the lean local stack.

## Open questions
- (none yet; agents add "verify" findings here, one line each)

## Relocks
- 13 Nov 2026 18:40: S0/S6/S9 allowed_paths gaps; uv-run command rule in prompts (Claude via chat) (changed: plan.yaml, plan/prompts/S0.md, plan/prompts/S1.md, plan/prompts/S10.md, plan/prompts/S2.md, plan/prompts/S3.md, plan/prompts/S4.md, plan/prompts/S5.md, plan/prompts/S6.md, plan/prompts/S7.md, plan/prompts/S8.md, plan/prompts/S9.md)

## S0 result
*Scaffold, uv tooling and the projects loader skeleton, 13 Nov 2026 18:48.*

Implementer `claude-tc-opus`; reviewers `cursor-grok`: pass; 0 fix loop(s); branch `factory/S0`.

| check | ok | detail |
|---|---|---|
| pyproject exists | yes |  |
| no apache-airflow in pyproject | yes |  |
| pyyaml dependency | yes |  |
| .gitignore has .env | yes |  |
| .gitignore has !.env.example | yes |  |
| .gitignore has stack/.env.generated | yes |  |
| .gitignore has stack/compose.projects.yaml | yes |  |
| .gitignore has logs/ | yes |  |
| .gitignore has .terraform/ | yes |  |
| .gitignore has .factory/ | yes |  |
| .tfstate ignored | yes |  |
| .gitattributes eol=lf | yes |  |
| projects.yaml exists | yes |  |
| CONTEXT.md and 3 ADRs present | yes |  |
| no secrets in repo files | yes |  |
| pytest tests | yes | 7 passed in 0.29s |
| required tests present | yes | 5 found |

Review: S0 matches its prompt. The uv project is Python 3.12 with pyyaml 6.0.3 and pytest 9.2.0; the lockfile contains no Airflow package. Gitignore covers .env, .env.*, !.env.example, stack/.env.generated, stack/compose.projects.yaml, logs/, *.tfstate*, .terraform/, and .factory/; .terraform.lock.hcl stays tracked. projects.py only reads YAML and the filesystem. load resolves dags.local against the YAML directory, and errors name the project and the field. The five required tests cover those rules. Render stubs raise NotImplementedError. The acceptance pass matches the files.

For Amir: NOTES.md S0 result still says uv.lock is missing and acceptance was not run. uv.lock is present and accept_s0 reported 7 passed in 0.29s. The plan.yaml and plan/prompts edits in the step diff are the 18:40 relock (S0 allowed_paths includes dags/; uv-run command rule), not loader code. STATUS.md still shows the earlier scope_violation stop from run 20261113-183318.

## Additions for S0
- The stack must run on Docker Desktop for Windows; scripts are PowerShell 7 (`pwsh`). Amir's laptop: check RAM headroom before starting other stacks (lineage-lab's OpenMetadata is heavy; stop it if `docker stats` shows pressure).
- The governor side (A1) is a separate plan in `../governor-airflow`; never touch it from this repo.

## Additions for S1
S1 adds image/, stack/, and stack.py. Keep pyproject free of apache-airflow; host dependencies stay pyyaml and pytest. The editable install points at src/, so python -m airflow_platform works. load(path) and validate(raw, base_dir) are done: DagSource.local is an absolute Path, git is a raw dict or None, and View and TaskLink are optional. render_bundles(projects, target='local') and render_compose_override(projects) raise NotImplementedError until S3. S3's signatures return list[dict] and dict, and the compose function takes registry_dir; update tests/test_projects.py::test_render_is_stubbed_until_s3 when replacing the stubs. projects/projects.yaml has only examples, with dags.local ../dags/examples. dags/examples/ contains .gitkeep only; hello_workload.py is S2. stack/.env.generated and stack/compose.projects.yaml are already gitignored. .terraform.lock.hcl is meant to be committed. Offline tests stay in tests/ and must not import Airflow.
