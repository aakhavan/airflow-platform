# NOTES archive

Sections rotated out of NOTES.md (PLAN.md §7.4), oldest first.

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

## Relocks
- 13 Nov 2026 19:40: isolation check: pandas removed from the denylist (it is a google-provider dependency shipped in the official base image, not project code); pip probed via python -m pip (base image PATH guard). Fixture: replaced a log path the secret scanner flagged as high-entropy with a placeholder. (via supervise, by Claude via chat (delegated by Amir)) (changed: plan/accept/_common.py, plan/accept/accept_s2.py)

## S1 result (implementer notes)
- Airflow **3.3.2** (`image/Dockerfile`, one `ARG AIRFLOW_VERSION`). Providers are installed with the official constraints-3.3.2/constraints-3.12.txt. `stack/compose.yaml` is the official 3.3.2 file, trimmed: LocalExecutor, no broker/worker/flower/cli, LOAD_EXAMPLES false, port `${AIRFLOW_PORT:-8080}`, and healthchecks everywhere.
- Auth manager: FAB, admin login airflow/airflow (the documented default, only in `stack/.env.example`).
- `airflow-init` is one-shot: `status` reports it as `ok` when it exited 0. Logs and config live in named volumes (`airflow-logs`, `airflow-config`). `../dags` and `../plugins` are bind mounts, and Docker creates an empty `plugins/` at the repo root until S4 fills it.
- `stack up` passes `--build` (cached), and compose output goes to `logs/stack-up.log`. `tests/fixtures/compose_ps.json` is a real recorded `docker compose ps -a --format json` (NDJSON on this Docker Desktop).
- Measured at idle: six services at 1231 MB RAM; image 3078 MiB.
- The stack is left running for S2. accept_s1 passed (20/20 checks; 15 tests).

## S2 result (implementer notes)
- `docker-proxy`: `tecnativa/docker-socket-proxy:v0.4.1` (in versions.yaml), env `CONTAINERS=1 IMAGES=1 POST=1`, no host port, healthcheck `wget http://127.0.0.1:2375/_ping`. The host socket is mounted read-only at `/run/docker.sock` inside the proxy with `SOCKET_PATH=/run/docker.sock`. The different target path keeps the socket path appearing exactly once in compose.yaml, which accept_s2 requires. No Airflow service mounts the socket. `docker-proxy` is now in `stack.EXPECTED`.
- `workloads/hello` (`python:3.12.12-slim`, runs as nobody) prints the greeting and `{"workload":"hello","ok":true,"python":"3.12.12"}`. `stack up` runs `docker build` for every `workloads/<name>/Dockerfile` as `airflow-platform/<name>:local` before compose up (logs in `logs/workload-<name>.log`).
- `dags/examples/hello_workload.py`: DockerOperator `hello`. `docker_url` comes from `Variable.get("docker_url", default="tcp://docker-proxy:2375")` at parse time. Item 4 needed no new mount, because S1 already bind-mounts the repo's `dags/` at `/opt/airflow/dags`, so `dags/examples/` loads from there (log: "Filling up the DagBag from /opt/airflow/dags/examples/hello_workload.py"). S3 replaces this with bundles.
- `stack.py`: `trigger` first unpauses the DAG (`PATCH /api/v2/dags/{id}` `is_paused=false`, because DAGs are paused at creation), then sends `POST /api/v2/dags/{id}/dagRuns` with `{"logical_date": null, "conf": {...}}`. `wait` polls `GET .../dagRuns/{run_id}` every 3 s until success or failed. `logs` reads `.../taskInstances/{task}` for `try_number`, then `.../logs/{try}?full_content=true`, and prints the last 20 lines. The token comes from `POST /auth/token` with the `.env` admin (default airflow/airflow) and is held only in memory. `status` adds `import_errors` from `airflow dags list-import-errors -o json` in the scheduler, which prints `[]` (verified); the value is -1 if the CLI can't be reached.
- Fixtures: `tests/fixtures/api_v2_hello.json` holds real trigger, run, task-instance and log responses, with ids, UUIDs and hostnames removed. `compose_ps.json` was re-recorded with docker-proxy.
- accept_s2: 11 of 12 checks pass, including the live run and the JSON line in the task log. `pip list in airflow image` fails, see Open questions (pip PATH and pandas). 20 tests pass.

## Additions for S0
- The stack must run on Docker Desktop for Windows; scripts are PowerShell 7 (`pwsh`). Amir's laptop: check RAM headroom before starting other stacks (lineage-lab's OpenMetadata is heavy; stop it if `docker stats` shows pressure).
- The governor side (A1) is a separate plan in `../governor-airflow`; never touch it from this repo.

## Additions for S1
S1 adds image/, stack/, and stack.py. Keep pyproject free of apache-airflow; host dependencies stay pyyaml and pytest. The editable install points at src/, so python -m airflow_platform works. load(path) and validate(raw, base_dir) are done: DagSource.local is an absolute Path, git is a raw dict or None, and View and TaskLink are optional. render_bundles(projects, target='local') and render_compose_override(projects) raise NotImplementedError until S3. S3's signatures return list[dict] and dict, and the compose function takes registry_dir; update tests/test_projects.py::test_render_is_stubbed_until_s3 when replacing the stubs. projects/projects.yaml has only examples, with dags.local ../dags/examples. dags/examples/ contains .gitkeep only; hello_workload.py is S2. stack/.env.generated and stack/compose.projects.yaml are already gitignored. .terraform.lock.hcl is meant to be committed. Offline tests stay in tests/ and must not import Airflow.

