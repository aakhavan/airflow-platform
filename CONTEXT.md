# CONTEXT: airflow-platform glossary

**Orchestrator**: Airflow itself (API server, scheduler, DAG processor, triggerer, metadata database). It schedules and launches work but never imports a project's code or libraries.

**Workload**: a container image plus a command that a DAG launches to do real work. All project logic and project dependencies live in workloads.

**Project**: a repository that plugs into the platform through one entry in `projects/projects.yaml`. It brings its own DAGs, workload images and, optionally, a UI. Governor is the first project.

**Project view**: a project's own UI shown inside the orchestrator's UI, as a nav entry, a DAG tab or a link from a task. The view is served by the project, not by the orchestrator.

**Target**: where the orchestrator runs: `local`, `aws` or `gcp`. Every target runs the same stack.

**Smoke test**: a short-lived cycle on a cloud target (create → run one DAG → destroy), protected by a time-to-live so that a forgotten machine deletes itself.

**Secret slot**: a named, empty place in a cloud secret store that the platform reads at boot. The platform creates slots; a person fills them.
