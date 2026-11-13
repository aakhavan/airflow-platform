#!/usr/bin/env pwsh
# Build the airflow-platform image and start the local stack (waits for health).
# Thin wrapper: all logic lives in python -m airflow_platform.stack.
$ErrorActionPreference = 'Stop'
Push-Location (Join-Path $PSScriptRoot '..')
try {
    uv run python -m airflow_platform.stack up
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
