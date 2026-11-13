# NOTES

## Current state
Spec, plan, prompts and acceptance scripts written 13 Nov 2026 (Claude chat, grilling session). Repo otherwise empty. Next: S0.

## Open questions
- (none yet; agents add "verify" findings here, one line each)

## Additions for S0
- The stack must run on Docker Desktop for Windows; scripts are PowerShell 7 (`pwsh`). Amir's laptop: check RAM headroom before starting other stacks (lineage-lab's OpenMetadata is heavy; stop it if `docker stats` shows pressure).
- The governor side (A1) is a separate plan in `../governor-airflow`; never touch it from this repo.
