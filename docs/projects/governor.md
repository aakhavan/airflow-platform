# Runbook: governor as a project

`governor` is the first real project on the platform (spec §6 and §8). Its DAG `governor_profile_raw` profiles the
`raw` schema of governor's Postgres test bed. The task is a `DockerOperator` that starts the existing `governor:local`
image through the platform's Docker socket proxy. The Airflow image gets no governor code (ADR 0001). The profile
lands on the governor data volume as `/data/profiles/<run id with ':' as '_'>.json`. The governor API serves it at
`GET /profiles/{run_id}`, and the Streamlit page **Profiles** shows it.

| piece | where | port |
|---|---|---|
| test bed Postgres (`shop`, schema `raw`) | `../governor-airflow/testbed` | 55432 |
| governor API / Streamlit UI | `../governor-airflow` (compose) | 8000 / 8501 |
| Airflow (this repo) | `stack/` | 8080 |

Until the `airflow-integration` branch is merged, everything governor-side runs from the worktree
`../governor-airflow`. See [After the merge](#after-the-merge).

## Start-up order

All commands run from `C:\Users\amir0\portfolio`. Run them in this order: the Airflow stack needs the image and the
volume, and the DAG needs the database.

1. **Test bed.** Start Postgres and load the Olist `raw` schema once. The details are in governor's
   `testbed/README.md`.
   ```powershell
   cd governor-airflow
   docker compose -f testbed/docker-compose.yml up -d --wait
   uv run python testbed/load_olist.py --source testbed/sample --dsn postgresql://governor_admin:governor_local@localhost:55432/shop
   uv run python testbed/apply_roles.py --dsn postgresql://governor_admin:governor_local@localhost:55432/shop
   ```
   `testbed/sample` holds the nine synthetic CSVs that ship with the repo, so this works on a clean
   laptop. Optional: to profile the real Olist data instead, download the Kaggle dataset into the
   git-ignored `testbed/data` as `testbed/README.md` describes, and rerun the load with
   `--source testbed/data`.
   `apply_roles.py` creates the `governor_build` login that the DAG uses. Its local default password is
   `governor_build_local`.
2. **Governor stack.** This step builds `governor:local` and creates the `governor-data` volume.
   First create the worktree's `.env` (git-ignored) from the template, with two local tokens. Paste
   `local-analyst` into the Profiles page when it asks for a token.
   ```powershell
   (Get-Content .env.example) -replace '<analyst-token>','local-analyst' -replace '<finance-admin-token>','local-admin' | Set-Content .env
   docker compose build
   docker compose up -d --wait
   ```
   Check that `http://localhost:8000/health` and `http://localhost:8501` answer.
3. **Airflow.** Run this from `airflow-platform`:
   ```powershell
   scripts/up.ps1          # or: uv run python -m airflow_platform.stack up
   ```
   `up` copies `stack/.env.example` to `stack/.env` if `stack/.env` is missing. It also renders the `governor` DAG
   bundle and its read-only mount. `uv run python -m airflow_platform.stack status --dags` should list
   `governor_profile_raw`.

## Variables

The DAG reads these Airflow Variables when the task runs. `stack/.env.example` sets them as `AIRFLOW_VAR_<NAME>`
environment variables. They don't appear in the UI's Variables list, but the DAG sees them.

| Variable | local default | used for |
|---|---|---|
| `docker_url` | `tcp://docker-proxy:2375` | the Docker API, through the proxy |
| `governor_data_volume` | `governor-airflow_governor-data` (worktree; `governor_governor-data` after the merge) | the volume mounted at `/data` |
| `governor_pg_host` / `_port` / `_db` | `host.docker.internal` / `55432` / `shop` | the test bed |
| `governor_build_user` / `_password` | `governor_build` / `governor_build_local` | the build login |

An existing `stack/.env` does not pick up new lines from `.env.example`. Copy the `AIRFLOW_VAR_*` lines across, or
delete `stack/.env` if you never edited it. Then run `up` again. Airflow checks environment variables before the metastore, so a
Variable with the same name set in the UI has no effect. To change a value, edit `stack/.env`.

## Trigger the DAG

- **UI:** open `http://localhost:8080`, log in as `airflow`/`airflow`, open **governor_profile_raw** (tag `governor`),
  then click **Trigger**. The DAG is manual only.
- **CLI:**
  ```powershell
  uv run python -m airflow_platform.stack trigger governor_profile_raw     # prints the run_id
  uv run python -m airflow_platform.stack wait governor_profile_raw <run_id>
  uv run python -m airflow_platform.stack logs governor_profile_raw <run_id> profile
  ```

## Open the report

- **Task link:** open the run, select the `profile` task, and click the **Open report** extra link. It points to
  `http://localhost:8501/Profiles?run_id=<run id>` (URL-quoted). The Profiles page reads `run_id` from the query
  string and asks the API for that profile. Paste your governor API token in the UI if it asks. The link exists only
  on DAGs whose id starts with `governor_`.
  CLI: `uv run python -m airflow_platform.stack links governor_profile_raw <run_id> profile`.
- **Governor view:** **Browse → Governor** in the Airflow nav, or the **Governor** tab on a DAG page, opens the
  Streamlit UI inside Airflow. In Airflow 3.3 the tab shows on every DAG.

## After the merge

When `airflow-integration` is merged into governor `main`:

1. In `projects/projects.yaml`, change `governor.dags.local` to `../../governor/airflow/dags`.
2. Start the test bed and the governor stack from `../governor` instead of `../governor-airflow`.
3. Set `AIRFLOW_VAR_GOVERNOR_DATA_VOLUME` to `governor_governor-data` in `stack/.env.example` and `stack/.env`
   (check the name first, see below), then run `up` again. The registry is read when the stack starts, so a change
   needs a restart.

## Troubleshooting

- **Volume name.** Compose names the volume `<project>_governor-data`, and the project name is the folder name
  unless `COMPOSE_PROJECT_NAME` is set. From `../governor-airflow` it is `governor-airflow_governor-data`, the
  current `.env.example` value. From `../governor` it is `governor_governor-data`, which is also the DAG's own
  fallback when the Variable is unset. Check with
  `docker volume ls --filter name=governor-data` and set `AIRFLOW_VAR_GOVERNOR_DATA_VOLUME` in `stack/.env` to
  match. A wrong name is not an error: Docker quietly creates a new empty volume, so the task succeeds, but the API
  and UI never see the profile (`404` on `/profiles/{run_id}`).
- **`host.docker.internal`.** The task container reaches the test bed through the host's published port 55432.
  The DAG adds `extra_hosts: host.docker.internal:host-gateway`, so this also works on Linux. A connection refused
  error means the test bed is down or uses a different port, so set `AIRFLOW_VAR_GOVERNOR_PG_PORT`. If you get an
  auth error, `apply_roles.py` hasn't run yet or the password differs.
- **Proxy sections.** The DAG goes through `docker-proxy` (`tecnativa/docker-socket-proxy`), which allows only
  `CONTAINERS`, `IMAGES` and `POST`. A `403` from the proxy means the call needs a section that is off. Turn it on
  in `stack/compose.yaml` only if a workload really needs it, and never turn on `EXEC`, `VOLUMES` or `SYSTEM`.
  `governor:local` is a local image, so if it is missing the pull fails. Build it first (step 2).
- **DAG missing.** `stack status --dags` shows the bundles. Check that `governor.dags.local` exists on the host and
  that you ran `up` after you changed the registry.
- **Report page empty.** The Profiles page lists stored profiles when `run_id` is unknown. Check the file with
  `curl -H "Authorization: Bearer <token>" http://localhost:8000/profiles`.
