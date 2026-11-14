#!/usr/bin/env pwsh
# Port-forward the VM's Airflow UI to localhost:<LocalPort> (docs/spec.md §10). Reads the instance from the
# Terraform outputs of terraform/envs/<target> and runs its tunnel_command:
#   aws: aws ssm start-session ... AWS-StartPortForwardingSession (needs the session-manager-plugin)
#   gcp: gcloud compute start-iap-tunnel <name> 8080 --local-host-port=localhost:<port> ...
# Runs in the foreground until Ctrl+C. smoke.ps1 runs it as a background job.
#   ./scripts/tunnel.ps1 -Target gcp
#   ./scripts/tunnel.ps1 -Target aws -LocalPort 18080
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][ValidateSet('aws', 'gcp')][string]$Target,
    [ValidateRange(1024, 65535)][int]$LocalPort = 8080
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_cloud.ps1')

Write-Host "tunnel.ps1: $Target VM port 8080 -> http://localhost:$LocalPort"
$outputs = Get-TfOutputs $Target
if ($null -eq $outputs) {
    Write-Host 'WhatIf: would read tunnel_command from the Terraform outputs and run it.'
    exit 0
}
if (-not $outputs.ContainsKey('tunnel_command') -or -not $outputs['tunnel_command']) {
    throw "terraform/envs/$Target has no tunnel_command output: nothing is deployed there."
}
$instance = if ($Target -eq 'aws') { $outputs['instance_id'] } else { $outputs['instance_name'] }
$tunnel = Get-TunnelArgs $Target $outputs['tunnel_command'] $LocalPort
Write-Host "instance: $instance. Ctrl+C closes the tunnel."
Invoke-Cloud -Exe $tunnel.Exe -Arguments $tunnel.Arguments -PassThru | Out-Null
