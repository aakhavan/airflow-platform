#!/usr/bin/env pwsh
# End-to-end smoke test of one cloud VM (docs/spec.md §10, docs/runbook.md). Costs real money (cents).
#   1. refuses if terraform/envs/<target> already has resources in state (unless -Force)
#   2. plans, prints the resources and a rough cost, asks for y (unless -Yes)
#   3. apply -var ttl_minutes=90 -var name=airflow-platform-smoke (the VM also deletes itself after 90 min)
#   4. waits for SSM (aws) / the instance to run for IAP (gcp)
#   5. opens the tunnel (scripts/tunnel.ps1) as a background job on localhost:<LocalPort>
#   6. stack status --url until healthy (15 min)
#   7. triggers hello_workload and waits for success
# finally (always, unless -KeepOnFailure and a phase failed): destroy -auto-approve, then looks for leftover
# instances named airflow-platform-smoke and fails loudly if any remain. Phases go to logs/smoke-<target>-<ts>.json.
#   ./scripts/smoke.ps1 -Target gcp
#   ./scripts/smoke.ps1 -Target aws -Yes -WhatIf   # prints every step, calls nothing
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][ValidateSet('aws', 'gcp')][string]$Target,
    [switch]$Yes,            # skip the y/N question
    [switch]$Force,          # run even if the env already has resources in state (they are destroyed at the end!)
    [switch]$KeepOnFailure,  # on failure, leave the VM up for debugging (destroy by hand: docs/runbook.md)
    [ValidateRange(1024, 65535)][int]$LocalPort = 18080  # not 8080, so the local dev stack keeps its port
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_cloud.ps1')

$SmokeName = 'airflow-platform-smoke'
$TtlMinutes = 90
$HealthTimeoutMinutes = 15
$WorkloadTimeoutSeconds = 600
$SmokeVars = @('-var', "ttl_minutes=$TtlMinutes", '-var', "name=$SmokeName")
if ($Target -eq 'aws') { $SmokeVars += @('-var', 'secret_recovery_window_days=0') }  # slots go at once on destroy

# Approximate prices (USD, on-demand, eu-central-1 / europe-west3, late 2026). Approximate: check the plan
# and the provider's price page; this only answers "cents or euros?".
$Prices = @{
    aws = @{
        hourly    = @{ 't3.medium' = 0.048; 't3a.medium' = 0.0432; 't3.large' = 0.096; 't3a.large' = 0.0864; 'm7i.large' = 0.1210 }
        diskGbMonth = 0.0952   # gp3
        extraHourly = 0.005    # public IPv4 address
        typeVar   = 'instance_type'
    }
    gcp = @{
        hourly    = @{ 'e2-medium' = 0.0436; 'e2-standard-2' = 0.0871; 'e2-standard-4' = 0.1742; 'n2-standard-2' = 0.1128 }
        diskGbMonth = 0.12     # pd-balanced
        extraHourly = 0.0014   # Cloud NAT gateway, per VM
        typeVar   = 'machine_type'
    }
}
$DiskGb = 30
$CostHours = 1.5

$stamp = Get-Stamp
$logFile = Join-Path $LogDir "smoke-$Target-$stamp.json"
$planFile = "smoke-$Target-$stamp.tfplan"
$url = "http://localhost:$LocalPort"
$phases = [System.Collections.Generic.List[object]]::new()
$tunnelJob = $null
$applied = $false
$failed = $false
$region = Get-TfVar $Target 'region' ($(if ($Target -eq 'aws') { 'eu-central-1' } else { 'europe-west3' }))
$project = if ($Target -eq 'gcp') { Get-TfVar $Target 'project_id' '<project_id>' } else { '' }

function Invoke-Phase([string]$Name, [scriptblock]$Body) {
    # Runs one phase, records status and seconds. Under -WhatIf the body only prints what it would do.
    $record = [ordered]@{ phase = $Name; status = 'running'; seconds = 0; detail = '' }
    $phases.Add($record)
    $clock = [System.Diagnostics.Stopwatch]::StartNew()
    Write-Host "== $Name"
    try {
        $detail = & $Body
        $record.status = if ($WhatIfPreference) { 'whatif' } else { 'ok' }
        if ($detail) { $record.detail = "$detail" }
    } catch {
        $record.status = 'failed'
        $record.detail = "$($_.Exception.Message)"
        throw
    } finally {
        $record.seconds = [math]::Round($clock.Elapsed.TotalSeconds, 1)
    }
}

function Get-StackLine([string[]]$Arguments) {
    # uv run python -m airflow_platform.stack <args>; the last JSON line as an object (or $null).
    $lines = Invoke-Cloud -Exe 'uv' -Arguments (@('run', 'python', '-m', 'airflow_platform.stack') + $Arguments) -AllowFailure
    $json = @($lines | Where-Object { $_ -match '^\s*\{' }) | Select-Object -Last 1
    if ($json) { return ($json | ConvertFrom-Json) }
    return $null
}

function Start-Tunnel {
    [CmdletBinding(SupportsShouldProcess)]
    param()
    $tunnelScript = Join-Path $PSScriptRoot 'tunnel.ps1'
    if (-not $PSCmdlet.ShouldProcess("tunnel.ps1 -Target $Target -LocalPort $LocalPort", 'start background job')) { return $null }
    Start-Job -Name "smoke-tunnel-$Target" -ScriptBlock {
        param($Path, $Cloud, $Port)
        & $Path -Target $Cloud -LocalPort $Port
    } -ArgumentList $tunnelScript, $Target, $LocalPort
}

Write-Host "smoke.ps1: $Target, name $SmokeName, ttl $TtlMinutes min, tunnel $url, log logs/smoke-$Target-$stamp.json"
if ($WhatIfPreference) { Write-Host 'WhatIf: every cloud, Terraform and tunnel call below is only printed.' }

try {
    Invoke-Phase 'preflight' {
        Assert-CliLogin -Target $Target
        if (-not (Test-TfVars $Target) -and -not $WhatIfPreference) { throw 'terraform.tfvars is required (repo_url, and project_id on gcp).' }
        Invoke-Terraform -Target $Target -Arguments @('init', '-input=false', '-no-color') -PassThru | Out-Null
        $state = Invoke-Terraform -Target $Target -Arguments @('state', 'list') -AllowFailure
        $existing = @($state | Where-Object { $_ -and $_ -notmatch '^data\.' -and $_ -notmatch '\.data\.' })
        if ($existing.Count -gt 0) {
            if (-not $Force) {
                throw "terraform/envs/$Target already has $($existing.Count) resources in state; refusing (use -Force: they are destroyed at the end)."
            }
            Write-Warning "-Force: $($existing.Count) existing resources in state WILL BE DESTROYED by the cleanup."
        }
        "existing resources: $($existing.Count)"
    }

    Invoke-Phase 'plan' {
        New-Item -ItemType Directory -Force $LogDir | Out-Null
        $lines = Invoke-Terraform -Target $Target -Arguments (@('plan', '-input=false', '-no-color', "-out=../../../logs/$planFile") + $SmokeVars)
        $headers = @($lines | Where-Object { $_ -match '^\s*# \S+ (will|must) be' } | ForEach-Object { $_.Trim().TrimStart('#').Trim() })
        $totals = @($lines | Where-Object { $_ -match '^Plan:' }) | Select-Object -Last 1
        if ($headers.Count) { Write-Host 'Resources:'; $headers | ForEach-Object { Write-Host "  $_" } }
        if ($totals) { Write-Host $totals }

        $price = $Prices[$Target]
        $type = Get-TfVar $Target $price.typeVar ''
        $hourly = if ($price.hourly.ContainsKey($type)) { $price.hourly[$type] } else { $null }
        if ($null -eq $hourly) {
            Write-Host "Cost: unknown for '$type' (not in the price table); check the plan and the price page."
        } else {
            $vm = ($hourly + $price.extraHourly) * $CostHours
            $disk = $DiskGb * $price.diskGbMonth / 730 * $CostHours
            Write-Host ('Cost (approximate, check the plan): {0} ${1:N3}/h x {2} h + {3} GB disk = about ${4:N2}' -f `
                $type, $hourly, $CostHours, $DiskGb, ($vm + $disk))
        }
        "$($headers.Count) resources"
    }

    if (-not $Yes -and -not $WhatIfPreference) {
        $answer = Read-Host "Apply $SmokeName to $Target now? [y/N]"
        if ($answer -ne 'y') {
            $phases.Add([ordered]@{ phase = 'confirm'; status = 'declined'; seconds = 0; detail = '' })
            Write-Host 'Not applied.'
            return
        }
    }

    Invoke-Phase 'apply' {
        $script:applied = $true  # from here on, the finally block cleans up (a half-made apply too)
        # -var ttl_minutes=90 -var name=airflow-platform-smoke are in the saved plan ($SmokeVars).
        Invoke-Terraform -Target $Target -Arguments @('apply', '-input=false', '-no-color', '-auto-approve', "../../../logs/$planFile") -PassThru | Out-Null
    }

    $outputs = Get-TfOutputs $Target
    $instance = if ($null -eq $outputs) { '<instance>' } elseif ($Target -eq 'aws') { $outputs['instance_id'] } else { $outputs['instance_name'] }
    $zone = if ($null -ne $outputs -and $outputs.ContainsKey('zone')) { $outputs['zone'] } else { Get-TfVar $Target 'zone' 'europe-west3-a' }

    Invoke-Phase 'wait-for-access' {
        if ($WhatIfPreference) {
            $null = Invoke-Cloud -Exe ($(if ($Target -eq 'aws') { 'aws' } else { 'gcloud' })) -Arguments @('<poll instance readiness>')
            return
        }
        $deadline = (Get-Date).AddMinutes(10)
        while ($true) {
            if ($Target -eq 'aws') {
                $ping = Invoke-Cloud -Exe 'aws' -Arguments @('ssm', 'describe-instance-information', '--region', $region,
                    '--filters', "Key=InstanceIds,Values=$instance", '--query', 'InstanceInformationList[0].PingStatus',
                    '--output', 'text') -AllowFailure
                if (($ping | Select-Object -First 1) -eq 'Online') { return "ssm online: $instance" }
            } else {
                $status = Invoke-Cloud -Exe 'gcloud' -Arguments @('compute', 'instances', 'describe', $instance, '--zone', $zone,
                    '--project', $project, '--format=value(status)') -AllowFailure
                if (($status | Select-Object -First 1) -eq 'RUNNING') { return "running: $instance (IAP)" }
            }
            if ((Get-Date) -gt $deadline) { throw "instance $instance not reachable for SSM/IAP after 10 min" }
            Start-Sleep -Seconds 15
        }
    }

    Invoke-Phase 'tunnel' {
        $script:tunnelJob = Start-Tunnel
        if ($script:tunnelJob) { "job $($script:tunnelJob.Id) on $url" }
    }

    Invoke-Phase 'health' {
        if ($WhatIfPreference) {
            $null = Invoke-Cloud -Exe 'uv' -Arguments @('run', 'python', '-m', 'airflow_platform.stack', 'status', '--url', $url)
            return
        }
        $deadline = (Get-Date).AddMinutes($HealthTimeoutMinutes)
        while ($true) {
            if ($script:tunnelJob.State -ne 'Running') {
                Write-Host "tunnel job $($script:tunnelJob.State); restarting it"
                Remove-Job -Force $script:tunnelJob
                $script:tunnelJob = Start-Tunnel
            }
            $line = Get-StackLine @('status', '--url', $url)
            if ($line -and $line.up) { return "healthy, airflow $($line.airflow_version)" }
            if ((Get-Date) -gt $deadline) { throw "stack not healthy on $url after $HealthTimeoutMinutes min" }
            Start-Sleep -Seconds 20
        }
    }

    Invoke-Phase 'hello_workload' {
        $run = Get-StackLine @('trigger', 'hello_workload', '--url', $url)
        if ($WhatIfPreference) {
            $null = Invoke-Cloud -Exe 'uv' -Arguments @('run', 'python', '-m', 'airflow_platform.stack', 'wait', 'hello_workload', '<run_id>', '--url', $url)
            return
        }
        if (-not $run -or -not $run.run_id) { throw "trigger failed: $($run | ConvertTo-Json -Compress)" }
        $done = Get-StackLine @('wait', 'hello_workload', $run.run_id, '--timeout', "$WorkloadTimeoutSeconds", '--url', $url)
        if (-not $done -or $done.state -ne 'success') { throw "hello_workload $($run.run_id) ended $($done.state)" }
        "run $($run.run_id) success"
    }
} catch {
    $failed = $true
    Write-Host "FAILED: $($_.Exception.Message)"
} finally {
    if ($tunnelJob) {
        Stop-Job $tunnelJob -ErrorAction SilentlyContinue
        Remove-Job -Force $tunnelJob -ErrorAction SilentlyContinue
    }
    $keep = $KeepOnFailure -and $failed
    if ($applied -and $keep) {
        $phases.Add([ordered]@{ phase = 'destroy'; status = 'skipped'; seconds = 0; detail = '-KeepOnFailure: destroy by hand (docs/runbook.md)' })
        Write-Warning "-KeepOnFailure: $SmokeName is still running and costing money. Destroy it by hand (docs/runbook.md)."
    } elseif ($applied) {
        try {
            Invoke-Phase 'destroy' {
                Invoke-Terraform -Target $Target -Arguments (@('destroy', '-input=false', '-no-color', '-auto-approve') + $SmokeVars) -PassThru | Out-Null
            }
        } catch {
            $failed = $true
            Write-Host "DESTROY FAILED: $($_.Exception.Message)"
        }
        try {
            Invoke-Phase 'leftovers' {
                if ($Target -eq 'aws') {
                    $left = Invoke-Cloud -Exe 'aws' -Arguments @('ec2', 'describe-instances', '--region', $region,
                        '--filters', "Name=tag:Name,Values=$SmokeName",
                        'Name=instance-state-name,Values=pending,running,stopping,stopped,shutting-down',
                        '--query', 'Reservations[].Instances[].InstanceId', '--output', 'text')
                } else {
                    $left = Invoke-Cloud -Exe 'gcloud' -Arguments @('compute', 'instances', 'list', '--project', $project,
                        "--filter=name=$SmokeName", '--format=value(name)')
                }
                $left = @($left | Where-Object { $_ -and $_.Trim() -and $_.Trim() -ne 'None' })
                if ($left.Count -gt 0) {
                    throw "LEFTOVER INSTANCES named $SmokeName are still there: $($left -join ', '). Delete them by hand (docs/runbook.md)."
                }
                'none'
            }
        } catch {
            $failed = $true
            Write-Host "!!! $($_.Exception.Message)" -ForegroundColor Red
        }
    }

    if ($WhatIfPreference) {
        Write-Host 'WhatIf: no smoke log was written.'
    } else {
        New-Item -ItemType Directory -Force $LogDir | Out-Null
        [ordered]@{ target = $Target; name = $SmokeName; started = $stamp; ok = (-not $failed); url = $url; phases = $phases } |
            ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 $logFile
        Write-Host "log: logs/smoke-$Target-$stamp.json"
    }
}
if ($failed) { exit 1 }
if ($WhatIfPreference) { Write-Host "WhatIf: smoke $Target was not run." } else { Write-Host "smoke $Target passed" }
