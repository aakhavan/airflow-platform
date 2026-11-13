# airflow-platform

A reusable, self-hosted Apache Airflow 3 platform: a thin orchestrator image (Airflow and providers only), workloads as their own containers, project DAGs loaded through DAG bundles from a `projects/projects.yaml` registry, and the same Docker Compose stack locally and on one VM per cloud (Terraform). Work in progress, built by the factory. The build contract is in [docs/spec.md](docs/spec.md).

## Projects

Each project is one entry in `projects/projects.yaml`: its DAG folder, plus an optional UI view and task link. For example, `governor` profiles a Postgres schema in its own container and links each run to its report ([runbook](docs/projects/governor.md)).

## Adding a project

Add one entry to `projects/projects.yaml` (`name` in `[a-z0-9-]`, `dags.local` relative to that file), then run `scripts/up.ps1`. `up` renders the git-ignored `stack/.env.generated` (the `LocalDagBundle` list) and `stack/compose.projects.yaml` (read-only mounts under `/opt/airflow/projects/<name>`). No platform code changes. `uv run python -m airflow_platform.stack status --dags` lists the active DAGs and their bundles.

## CI

`.github/workflows/ci.yml` runs on every push and pull request, with no secrets: a `python` job (`uv sync --frozen`, `pytest -q`) and a `stack` job that starts the stack with `projects/ci.yaml` (the `examples` project only), checks for zero DAG import errors, runs `hello_workload` to `success`, and always tears down with volumes. On failure it uploads the `docker compose logs` as an artifact.

To reproduce the stack job locally, run `pwsh scripts/ci-local.ps1`. It uses its own compose project (`airflow_platform_ci`) on port 8081, with its generated files under `logs/airflow_platform_ci/`, so the dev stack (`airflow_platform`, 8080) keeps running and is left as it was. Every `python -m airflow_platform.stack` subcommand takes `--compose-project` and `--port` for the same reason.
