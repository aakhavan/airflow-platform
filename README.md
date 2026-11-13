# airflow-platform

A reusable, self-hosted Apache Airflow 3 platform: a thin orchestrator image (Airflow and providers only), workloads as their own containers, project DAGs loaded through DAG bundles from a `projects/projects.yaml` registry, and the same Docker Compose stack locally and on one VM per cloud (Terraform). Work in progress, built by the factory. The build contract is in [docs/spec.md](docs/spec.md).
