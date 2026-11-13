# 0003: Project views are external views and task links, not React plugins

**Status:** accepted, 13 Nov 2026

## Context
Projects (governor first) have their own UI and want to appear inside Airflow's UI, so that a user can go from a DAG run to the project's report. Airflow 3.1+ plugins offer external views (an iframe or link), React apps, FastAPI apps and operator extra links. Plugin Python code runs inside Airflow's API server process.

## Decision
A project view is an **external view** (a nav entry plus a DAG tab, iframing the project's own UI) and an **operator extra link** that deep-links a task instance to the project's page for that run. Both are generated from `projects.yaml` by one generic platform plugin. Projects serve their UI themselves.

## Considered options
- **React app plugins.** They look most native, but they are marked experimental in Airflow 3.1+, share React with the host so versions must match, and their backend would run in Airflow's process (breaking ADR 0001).
- **A project-specific plugin per project.** That puts project code in the orchestrator, and every project must learn the plugin API.
- **External views plus links, generated from YAML (chosen).** No project code in Airflow, and a project's UI can change technology (Streamlit today, a proper front end later) without touching Airflow.

## Consequences
- The iframe only works where the browser can reach the project's UI (locally `localhost:8501`; in the cloud through the same tunnel).
- The look is "embedded", not native. Accepted for now.
- A future React plugin is still possible behind the same `projects.yaml` entry if the API stabilises.
