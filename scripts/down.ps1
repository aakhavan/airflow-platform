#!/usr/bin/env pwsh
# Stop the local stack. Volumes (Postgres data, logs) are kept unless -Volumes is given.
# Thin wrapper: all logic lives in python -m airflow_platform.stack.
param([switch]$Volumes)
$ErrorActionPreference = 'Stop'
Push-Location (Join-Path $PSScriptRoot '..')
try {
    $extra = @()
    if ($Volumes) { $extra += '--volumes' }
    uv run python -m airflow_platform.stack down @extra
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
