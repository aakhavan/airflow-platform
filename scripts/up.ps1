#!/usr/bin/env pwsh
# Render the generated files from projects/projects.yaml (stack/.env.generated, stack/compose.projects.yaml),
# build the images and start the local stack (waits for health). `stack up` runs `render` first.
# Thin wrapper: all logic lives in python -m airflow_platform.stack.
#   ./scripts/up.ps1                       # default registry projects/projects.yaml
#   ./scripts/up.ps1 -Projects other.yaml  # another registry
param([string]$Projects = 'projects/projects.yaml')
$ErrorActionPreference = 'Stop'
Push-Location (Join-Path $PSScriptRoot '..')
try {
    uv run python -m airflow_platform.stack up --projects $Projects
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
