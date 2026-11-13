# AGENTS.md: rules for every agent in this repo

This repo is **airflow-platform**, a reusable self-hosted Airflow platform built step by step by the code factory. Your step prompt names the section of `docs/spec.md` to read. Read that, not whole documents. Vocabulary is in `CONTEXT.md`.

## Hard rules
- **Never commit, push, branch or stash.** The factory commits.
- **Never read `.env`, `.env.*` (except `.env.example`) or `stack/.env.generated` beyond what your step writes.** Never print, log or write a key, password or token. The only credentials allowed in files are the documented local defaults of the official Airflow compose file and of governor's test bed (`../governor/testbed/README.md`), and only in `stack/.env.example`.
- **Change only the paths your step allows** (plus `NOTES.md`). Never edit `plan/`, which is locked.
- **Never change anything in `../governor`, `../governor-airflow`, `../olist-dbt` or `../lineage-lab`.** Read them only.
- **The thin-orchestrator rule (ADR 0001):** the Airflow image gets Airflow and providers only, installed with the official constraints file. Never add project libraries (dbt, langchain, pandas, streamlit, governor) to `image/`. Workloads are containers.
- **Python on the host:** 3.12 + uv, for tooling and tests only (`pyyaml`, `pytest`). Never add `apache-airflow` to `pyproject.toml`. Code that needs Airflow runs inside the containers.
- **Docker:** only the compose project `airflow_platform`, plus images you build here. You may *read* (never stop, remove or change) the governor test bed and governor stack containers and volumes. Never `docker system prune` or `docker volume rm` anything you didn't create.
- **Cloud:** never run `terraform apply`, `plan` against a real provider, `aws` or `gcloud` commands that touch an account, `plan.ps1` or `smoke.ps1` without `-WhatIf`. Terraform runs only as `fmt`, `validate`, `init -backend=false` and `test` with mock providers.
- **Tests:** tests under `tests/` run offline (no Docker, no network, no Airflow import), on pure functions and small fixtures. Live checks live in the acceptance scripts and in `python -m airflow_platform.stack ...`, which prints one JSON line last.
- **"Verify" items:** the spec marks some facts "verify" (§12). When the real tool differs, follow the tool and write one line under "Open questions" in `NOTES.md`. Never fake a result to make a check pass.
- **Windows:** scripts are PowerShell 7 (`pwsh`), with LF line endings (`.gitattributes`). Paths in YAML use forward slashes.

## Output rules
- Quiet commands; logs go to `logs/` (git-ignored); paste summaries, not logs.
- `NOTES.md`: add a short "<step> result" when you finish, and any "Open questions".
- Never read whole: `uv.lock`, `*.tfstate*`, `.terraform/`, `logs/`, `.factory/`, `NOTES-archive.md`.
