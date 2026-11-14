#!/usr/bin/env pwsh
# terraform init + plan in terraform/envs/<target> with your own CLI login (docs/spec.md §10, docs/runbook.md).
# Read-only against the cloud: nothing is created. The plan file and a summary go to logs/.
#   ./scripts/plan.ps1 -Target aws
#   ./scripts/plan.ps1 -Target gcp -WhatIf   # prints what it would run, calls nothing
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][ValidateSet('aws', 'gcp')][string]$Target
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_cloud.ps1')

$stamp = Get-Stamp
$planFile = "plan-$Target-$stamp.tfplan"
$summaryFile = Join-Path $LogDir "plan-$Target-$stamp.txt"
Write-Host "plan.ps1: terraform init + plan in terraform/envs/$Target; summary -> logs/plan-$Target-$stamp.txt"

Assert-CliLogin -Target $Target
$null = Test-TfVars $Target

Invoke-Terraform -Target $Target -Arguments @('init', '-input=false', '-no-color') -PassThru | Out-Null
New-Item -ItemType Directory -Force $LogDir | Out-Null
$planArgs = @('plan', '-input=false', '-no-color', "-out=../../../logs/$planFile")
$lines = Invoke-Terraform -Target $Target -Arguments $planArgs
if ($null -eq $lines) {
    Write-Host 'WhatIf: no plan was made and no summary was written.'
    exit 0
}

# Summary: the resource headers ("# ... will be created") and the totals line. Values stay in the plan file.
$summary = @($lines | Where-Object { $_ -match '^\s*# \S+ (will|must) be' -or $_ -match '^(Plan:|No changes\.)' })
@("target: $Target", "plan file: logs/$planFile", "made: $stamp", '') + $summary |
    Set-Content -Encoding utf8 $summaryFile
$summary | Select-Object -Last 1 | Write-Host
Write-Host "summary: logs/plan-$Target-$stamp.txt"
