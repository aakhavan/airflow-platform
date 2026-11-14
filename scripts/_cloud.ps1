# Shared helpers for the cloud scripts (plan, smoke, tunnel, remote-state). Dot-source it:
#   . (Join-Path $PSScriptRoot '_cloud.ps1')
# Every call that reaches a cloud or Terraform goes through Invoke-Cloud, which honours -WhatIf:
# under -WhatIf nothing is run, the command line is only printed. No helper ever prints a secret value.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$script:LogDir = Join-Path $script:RepoRoot 'logs'
$script:TerraformImage = 'hashicorp/terraform:1.13'  # used only when terraform is not on PATH
$script:CloudExitCode = 0  # exit code of the last Invoke-Cloud

function Get-EnvDir([string]$Target) {
    Join-Path $script:RepoRoot "terraform/envs/$Target"
}

function Get-Stamp {
    (Get-Date).ToString('yyyyMMdd-HHmmss')
}

function Test-Cli([string]$Name) {
    [bool](Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue)
}

function Format-CommandLine([string]$Exe, [string[]]$Arguments) {
    (@($Exe) + @($Arguments | ForEach-Object { if ($_ -match '\s') { "'$_'" } else { $_ } })) -join ' '
}

function Invoke-Cloud {
    # Runs one external command (aws, gcloud, terraform, docker) unless -WhatIf is in effect.
    # Returns stdout lines; throws on a non-zero exit unless -AllowFailure.
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(Mandatory)][string]$Exe,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory = $script:RepoRoot,
        [switch]$AllowFailure,
        [switch]$PassThru  # stream output to the console instead of capturing it
    )
    $line = Format-CommandLine $Exe $Arguments
    if (-not $PSCmdlet.ShouldProcess($line, 'run')) { return $null }
    $out = @()
    $err = @()
    Push-Location $WorkingDirectory
    try {
        if ($PassThru) {
            & $Exe @Arguments | Out-Host
        } else {
            $all = @(& $Exe @Arguments 2>&1)
            $out = @($all | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] } | ForEach-Object { "$_" })
            $err = @($all | Where-Object { $_ -is [System.Management.Automation.ErrorRecord] } | ForEach-Object { "$_" })
        }
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    $script:CloudExitCode = $code
    if ($code -ne 0 -and -not $AllowFailure) {
        $what = (@($Exe) + @($Arguments | Where-Object { $_ -notmatch '^-' } | Select-Object -First 3)) -join ' '
        throw "'$what' exited $code. $(($err | Select-Object -Last 3) -join ' | ')"
    }
    return $out
}

function Get-TerraformCommand([string]$Target) {
    # terraform on PATH, else the pinned docker image with the repo mounted and the CLI login passed in.
    $envDir = Get-EnvDir $Target
    if (Test-Cli 'terraform') {
        return [pscustomobject]@{ Exe = 'terraform'; Prefix = @(); WorkingDirectory = $envDir }
    }
    $mount = ($script:RepoRoot -replace '\\', '/')
    $prefix = @('run', '--rm', '-i', '-v', "${mount}:/repo", '-w', "/repo/terraform/envs/$Target")
    if ($Target -eq 'aws') {
        $awsDir = Join-Path $HOME '.aws'
        if (Test-Path $awsDir) { $prefix += @('-v', "$(($awsDir -replace '\\', '/')):/root/.aws") }
        foreach ($name in 'AWS_PROFILE', 'AWS_REGION', 'AWS_DEFAULT_REGION') {
            if (Test-Path "env:$name") { $prefix += @('-e', $name) }
        }
    } else {
        $gcloudDir = if ($env:APPDATA) { Join-Path $env:APPDATA 'gcloud' } else { Join-Path $HOME '.config/gcloud' }
        if (Test-Path $gcloudDir) { $prefix += @('-v', "$(($gcloudDir -replace '\\', '/')):/root/.config/gcloud") }
        foreach ($name in 'CLOUDSDK_CORE_PROJECT', 'GOOGLE_CLOUD_PROJECT') {
            if (Test-Path "env:$name") { $prefix += @('-e', $name) }
        }
    }
    $prefix += $script:TerraformImage
    return [pscustomobject]@{ Exe = 'docker'; Prefix = $prefix; WorkingDirectory = $script:RepoRoot }
}

function Invoke-Terraform {
    # terraform <args> in terraform/envs/<target>. Paths in <args> must be relative to that folder.
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(Mandatory)][string]$Target,
        [string[]]$Arguments = @(),
        [switch]$AllowFailure,
        [switch]$PassThru
    )
    $tf = Get-TerraformCommand $Target
    Invoke-Cloud -Exe $tf.Exe -Arguments (@($tf.Prefix) + @($Arguments)) -WorkingDirectory $tf.WorkingDirectory `
        -AllowFailure:$AllowFailure -PassThru:$PassThru
}

function Get-TfVar([string]$Target, [string]$Name, [string]$Default = '') {
    # A string value from terraform/envs/<target>/terraform.tfvars, else variables.tf's default, else $Default.
    $envDir = Get-EnvDir $Target
    foreach ($file in (Join-Path $envDir 'terraform.tfvars'), (Join-Path $envDir 'variables.tf')) {
        if (-not (Test-Path $file)) { continue }
        $text = Get-Content -Raw $file
        if ($file.EndsWith('.tfvars')) {
            $m = [regex]::Match($text, "(?m)^\s*$Name\s*=\s*""([^""]*)""")
        } else {
            $m = [regex]::Match($text, "(?s)variable\s+""$Name""\s*\{[^}]*?default\s*=\s*""([^""]*)""")
        }
        if ($m.Success) { return $m.Groups[1].Value }
    }
    return $Default
}

function Test-TfVars([string]$Target) {
    $file = Join-Path (Get-EnvDir $Target) 'terraform.tfvars'
    if (Test-Path $file) { return $true }
    Write-Warning "terraform/envs/$Target/terraform.tfvars is missing: copy terraform.tfvars.example and fill it in (docs/runbook.md)."
    return $false
}

function Assert-CliLogin {
    # Checks the cloud CLI is installed and logged in. Prints only the account id (aws) or the email (gcp).
    [CmdletBinding(SupportsShouldProcess)]
    param([Parameter(Mandatory)][string]$Target)
    $cli = if ($Target -eq 'aws') { 'aws' } else { 'gcloud' }
    if (-not (Test-Cli $cli)) {
        if ($WhatIfPreference) { Write-Warning "$cli CLI not found on PATH (needed for a real run)."; return }
        throw "$cli CLI not found on PATH; install it and log in (docs/runbook.md)."
    }
    if ($Target -eq 'aws') {
        $id = Invoke-Cloud -Exe 'aws' -Arguments @('sts', 'get-caller-identity', '--query', 'Account', '--output', 'text')
        if ($null -ne $id) { Write-Host "aws: logged in, account $(($id | Select-Object -First 1).Trim())" }
    } else {
        $who = Invoke-Cloud -Exe 'gcloud' -Arguments @('auth', 'list', '--filter=status:ACTIVE', '--format=value(account)')
        if ($null -ne $who) {
            $email = ($who | Where-Object { $_ } | Select-Object -First 1)
            if (-not $email) { throw 'gcloud: no active account; run gcloud auth login and gcloud auth application-default login.' }
            Write-Host "gcloud: logged in as $email"
        }
    }
}

function Get-TfOutputs([string]$Target) {
    # terraform output -json as a hashtable of name -> value ($null under -WhatIf).
    $raw = Invoke-Terraform -Target $Target -Arguments @('output', '-json')
    if ($null -eq $raw) { return $null }
    $parsed = ($raw -join "`n") | ConvertFrom-Json -AsHashtable
    $values = @{}
    foreach ($k in $parsed.Keys) { $values[$k] = $parsed[$k].value }
    return $values
}

function Get-TunnelArgs([string]$Target, [string]$TunnelCommand, [int]$LocalPort) {
    # The tunnel_command output (no quoted parts) as exe + args, with the local port swapped in.
    $parts = @($TunnelCommand -split '\s+' | Where-Object { $_ })
    if ($parts.Count -lt 2) { throw "unexpected tunnel_command: $TunnelCommand" }
    $rest = @($parts | Select-Object -Skip 1 | ForEach-Object {
            $_ -replace 'localPortNumber=\d+', "localPortNumber=$LocalPort" `
               -replace '--local-host-port=localhost:\d+', "--local-host-port=localhost:$LocalPort"
        })
    [pscustomobject]@{ Exe = $parts[0]; Arguments = $rest }
}
