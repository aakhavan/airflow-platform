#!/usr/bin/env pwsh
# Render the generated files from projects/projects.yaml (stack/.env.generated, stack/compose.projects.yaml),
# build the images and start the local stack (waits for health). `stack up` runs `render` first.
# Thin wrapper: all logic lives in python -m airflow_platform.stack.
#   ./scripts/up.ps1                       # default registry projects/projects.yaml
#   ./scripts/up.ps1 -Projects other.yaml  # another registry
#   ./scripts/up.ps1 -Projects projects/ci.yaml -ComposeProject airflow_platform_ci -Port 8081  # a second stack
param(
    [string]$Projects = 'projects/projects.yaml',
    [string]$ComposeProject = 'airflow_platform',
    [int]$Port = 0  # 0: AIRFLOW_PORT from stack/.env, else 8080
)
$ErrorActionPreference = 'Stop'
Push-Location (Join-Path $PSScriptRoot '..')
try {
    $extra = @('--compose-project', $ComposeProject)
    if ($Port -gt 0) { $extra += @('--port', "$Port") }
    uv run python -m airflow_platform.stack up --projects $Projects @extra
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
