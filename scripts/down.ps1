#!/usr/bin/env pwsh
# Stop the local stack. Volumes (Postgres data, logs) are kept unless -Volumes is given.
# Thin wrapper: all logic lives in python -m airflow_platform.stack.
#   ./scripts/down.ps1 -Volumes -ComposeProject airflow_platform_ci   # only the CI stack
param(
    [switch]$Volumes,
    [string]$ComposeProject = 'airflow_platform',
    [int]$Port = 0  # 0: AIRFLOW_PORT from stack/.env, else 8080
)
$ErrorActionPreference = 'Stop'
Push-Location (Join-Path $PSScriptRoot '..')
try {
    $extra = @('--compose-project', $ComposeProject)
    if ($Port -gt 0) { $extra += @('--port', "$Port") }
    if ($Volumes) { $extra += '--volumes' }
    uv run python -m airflow_platform.stack down @extra
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
