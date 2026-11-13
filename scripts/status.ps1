#!/usr/bin/env pwsh
# Print the local stack status as one JSON line (up, services, airflow_version, url, mem_mb).
# Thin wrapper: all logic lives in python -m airflow_platform.stack.
$ErrorActionPreference = 'Stop'
Push-Location (Join-Path $PSScriptRoot '..')
try {
    uv run python -m airflow_platform.stack status
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
