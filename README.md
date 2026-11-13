# airflow-platform

A reusable, self-hosted Apache Airflow 3 platform: a thin orchestrator image (Airflow and providers only), workloads as their own containers, project DAGs loaded through DAG bundles from a `projects/projects.yaml` registry, and the same Docker Compose stack locally and on one VM per cloud (Terraform). Work in progress, built by the factory. The build contract is in [docs/spec.md](docs/spec.md).

## Projects

Each project is one entry in `projects/projects.yaml`: its DAG folder, plus an optional UI view and task link. For example, `governor` profiles a Postgres schema in its own container and links each run to its report ([runbook](docs/projects/governor.md)).

## Adding a project

Add one entry to `projects/projects.yaml` (`name` in `[a-z0-9-]`, `dags.local` relative to that file), then run `scripts/up.ps1`. `up` renders the git-ignored `stack/.env.generated` (the `LocalDagBundle` list) and `stack/compose.projects.yaml` (read-only mounts under `/opt/airflow/projects/<name>`). No platform code changes. `uv run python -m airflow_platform.stack status --dags` lists the active DAGs and their bundles.
