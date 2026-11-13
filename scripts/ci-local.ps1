#!/usr/bin/env pwsh
# Run the CI `stack` job (.github/workflows/ci.yml, docs/spec.md §11) on this machine.
# It never touches the dev stack: its own compose project (airflow_platform_ci), port 8081, and its generated
# files under logs/airflow_platform_ci/ (the dev stack's stack/.env.generated and compose.projects.yaml stay as they are).
# Sequence: up (CI registry, examples only) -> status: import_errors == 0 -> trigger hello_workload -> wait success
# -> always down -Volumes. On failure, compose logs go to logs/compose-airflow_platform_ci.log.
#   ./scripts/ci-local.ps1
param(
    [string]$Projects = 'projects/ci.yaml',
    [string]$ComposeProject = 'airflow_platform_ci',
    [int]$Port = 8081,
    [int]$WaitTimeout = 300
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($ComposeProject -eq 'airflow_platform') { throw 'ci-local.ps1 must not use the dev compose project airflow_platform' }

function Invoke-Stack([string[]]$StackArgs) {
    # python -m airflow_platform.stack <args>; returns the last JSON line as an object (exit code in $LASTEXITCODE).
    $out = @(uv run python -m airflow_platform.stack @StackArgs)
    $code = $LASTEXITCODE
    $line = $out | Where-Object { "$_".TrimStart().StartsWith('{') } | Select-Object -Last 1
    Write-Host "stack $($StackArgs[0]): $line"
    $global:LASTEXITCODE = $code
    if ($line) { return ($line | ConvertFrom-Json) }
    return $null
}

$target = @('--compose-project', $ComposeProject, '--port', "$Port")

function Invoke-Sequence {
    # Returns $null on success, else the reason.
    & (Join-Path $PSScriptRoot 'up.ps1') -Projects $Projects -ComposeProject $ComposeProject -Port $Port | Write-Host
    if ($LASTEXITCODE -ne 0) { return 'up failed' }

    $status = Invoke-Stack (@('status', '--projects', $Projects) + $target)
    if (-not $status -or -not $status.up) { return 'stack is not up' }
    if ($status.import_errors -ne 0) { return "import_errors = $($status.import_errors)" }

    $run = Invoke-Stack (@('trigger', 'hello_workload') + $target)
    if ($LASTEXITCODE -ne 0 -or -not $run -or -not $run.run_id) { return 'trigger failed' }

    $done = Invoke-Stack (@('wait', 'hello_workload', $run.run_id, '--timeout', "$WaitTimeout") + $target)
    if ($LASTEXITCODE -ne 0 -or -not $done -or $done.state -ne 'success') {
        return "hello_workload ended in state $(if ($done) { $done.state } else { 'unknown' })"
    }
    return $null
}

$failed = $null
Push-Location (Join-Path $PSScriptRoot '..')
try {
    $failed = Invoke-Sequence
} catch {
    $failed = "error: $_"
} finally {
    if ($failed) { $null = Invoke-Stack (@('compose-logs') + $target) }
    & (Join-Path $PSScriptRoot 'down.ps1') -Volumes -ComposeProject $ComposeProject -Port $Port | Write-Host
    Pop-Location
}
if ($failed) {
    Write-Host "ci-local: FAIL ($failed); logs in logs/compose-$ComposeProject.log"
    exit 1
}
Write-Host 'ci-local: PASS (import_errors 0, hello_workload success, stack removed)'
exit 0
