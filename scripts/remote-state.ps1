#!/usr/bin/env pwsh
# Move terraform/envs/<target> to a remote state bucket (docs/spec.md §10):
#   1. creates the bucket if it is missing: private, versioned, encrypted
#      aws: S3 with block-public-access (all four), versioning, SSE (AES256), bucket-owner-enforced
#      gcp: GCS with uniform bucket-level access, public access prevention, versioning (Google-managed encryption)
#   2. writes terraform/envs/<target>/backend.tf
#   3. runs terraform init -migrate-state (copies the local state into the bucket)
# backend.tf is git-ignored-by-choice: committing it is Amir's decision (the bucket name is not a secret).
#   ./scripts/remote-state.ps1 -Target aws -Bucket my-tfstate-1234
#   ./scripts/remote-state.ps1 -Target gcp -Bucket my-tfstate-1234 -WhatIf
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][ValidateSet('aws', 'gcp')][string]$Target,
    [Parameter(Mandatory)][string]$Bucket,
    [string]$Region = '',   # default: region from terraform.tfvars, else the env default
    [string]$Project = ''   # gcp only; default: project_id from terraform.tfvars
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_cloud.ps1')

# S3 and GCS share the basic rule: 3-63 characters, lowercase letters, digits, dots and dashes.
if ($Bucket -notmatch '^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$') {
    if (-not $WhatIfPreference) { throw "invalid bucket name '$Bucket' (3-63 chars: a-z 0-9 . -)" }
    Write-Warning "bucket name '$Bucket' is not valid for a real run (3-63 chars: a-z 0-9 . -)."
}
if (-not $Region) { $Region = Get-TfVar $Target 'region' ($(if ($Target -eq 'aws') { 'eu-central-1' } else { 'europe-west3' })) }
if ($Target -eq 'gcp' -and -not $Project) { $Project = Get-TfVar $Target 'project_id' '<project_id>' }
$backendFile = Join-Path (Get-EnvDir $Target) 'backend.tf'
Write-Host "remote-state.ps1: $Target bucket '$Bucket' in $Region; writes terraform/envs/$Target/backend.tf; migrates the state."

Assert-CliLogin -Target $Target

if ($Target -eq 'aws') {
    $null = Invoke-Cloud -Exe 'aws' -Arguments @('s3api', 'head-bucket', '--bucket', $Bucket) -AllowFailure
    $exists = ($CloudExitCode -eq 0) -and -not $WhatIfPreference
    if (-not $exists) {
        $create = @('s3api', 'create-bucket', '--bucket', $Bucket, '--region', $Region, '--object-ownership', 'BucketOwnerEnforced')
        if ($Region -ne 'us-east-1') { $create += @('--create-bucket-configuration', "LocationConstraint=$Region") }
        $null = Invoke-Cloud -Exe 'aws' -Arguments $create
    }
    $null = Invoke-Cloud -Exe 'aws' -Arguments @('s3api', 'put-public-access-block', '--bucket', $Bucket,
        '--public-access-block-configuration',
        'BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true')
    $null = Invoke-Cloud -Exe 'aws' -Arguments @('s3api', 'put-bucket-versioning', '--bucket', $Bucket,
        '--versioning-configuration', 'Status=Enabled')
    $null = Invoke-Cloud -Exe 'aws' -Arguments @('s3api', 'put-bucket-encryption', '--bucket', $Bucket,
        '--server-side-encryption-configuration', '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}')
    $backend = @"
# Written by scripts/remote-state.ps1. Committing it is Amir's choice.
terraform {
  backend "s3" {
    bucket       = "$Bucket"
    key          = "airflow-platform/aws/terraform.tfstate"
    region       = "$Region"
    encrypt      = true
    use_lockfile = true
  }
}
"@
} else {
    $null = Invoke-Cloud -Exe 'gcloud' -Arguments @('storage', 'buckets', 'describe', "gs://$Bucket", '--project', $Project,
        '--format=value(name)') -AllowFailure
    $exists = ($CloudExitCode -eq 0) -and -not $WhatIfPreference
    if (-not $exists) {
        $null = Invoke-Cloud -Exe 'gcloud' -Arguments @('storage', 'buckets', 'create', "gs://$Bucket", '--project', $Project,
            '--location', $Region, '--uniform-bucket-level-access', '--public-access-prevention')
    }
    $null = Invoke-Cloud -Exe 'gcloud' -Arguments @('storage', 'buckets', 'update', "gs://$Bucket", '--project', $Project,
        '--versioning', '--uniform-bucket-level-access', '--public-access-prevention')
    $backend = @"
# Written by scripts/remote-state.ps1. Committing it is Amir's choice.
terraform {
  backend "gcs" {
    bucket = "$Bucket"
    prefix = "airflow-platform/gcp"
  }
}
"@
}

if ($PSCmdlet.ShouldProcess($backendFile, 'write backend.tf')) {
    Set-Content -Encoding utf8NoBOM -NoNewline -Path $backendFile -Value (($backend -replace "`r`n", "`n") + "`n")
    Write-Host "wrote terraform/envs/$Target/backend.tf"
} else {
    Write-Host "WhatIf: backend.tf would be:`n$backend"
}
Invoke-Terraform -Target $Target -Arguments @('init', '-input=false', '-migrate-state', '-force-copy') -PassThru | Out-Null

Write-Host ''
Write-Host "Reminder: committing terraform/envs/$Target/backend.tf is Amir's choice. It holds only the bucket name;"
Write-Host 'without it, every clone starts with local state again. The offline test test_no_backend_block_in_envs'
Write-Host 'fails while it exists in the working tree, so keep it out of CI checkouts unless that test changes.'
