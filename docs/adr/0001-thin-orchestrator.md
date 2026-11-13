# 0001: Thin orchestrator: workloads run as containers, not as Python inside Airflow

**Status:** accepted, 13 Nov 2026

## Context
Most Airflow pain comes from installing project libraries (dbt, LangChain, pandas, cloud SDKs) into the same Python environment as Airflow and its providers. Airflow pins hundreds of packages through its constraints file, project libraries pin their own, and every upgrade on either side breaks the other. The same pain repeats on every server and every managed service.

## Decision
The Airflow image contains Airflow and providers only, installed with the official constraints file. Every unit of project work is a **workload**: its own container image, launched by `DockerOperator` locally and on a VM (and by ECS / Cloud Run / Kubernetes pod operators if a target ever needs them). DAG files import only Airflow, providers and the standard library.

## Considered options
- **One image with everything, pinned with the constraints file.** Simplest, and the source of the pain.
- **Per-task virtualenvs** (`PythonVirtualenvOperator`, `ExternalPythonOperator`). They isolate, but they are slow, fragile on managed services, and still share the base interpreter.
- **Containers per workload (chosen).** One more layer (an image per project), in exchange for zero dependency coupling and identical behaviour on every target.

## Consequences
- An Airflow upgrade never touches project code, and a project upgrade never touches Airflow.
- Each project must ship an image. Governor already does.
- The Docker socket is a privilege: Airflow reaches Docker through a socket proxy with limited API sections, never the raw socket.
- An acceptance check enforces the rule (a denylist of project libraries in the Airflow image).
