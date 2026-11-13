# One-time kickoff for the airflow-platform factory run. Run from C:\Users\amir0\portfolio\airflow-platform in PowerShell 7.
# Does: git init + first commit here; governor worktree on branch airflow-integration; copies the A1 plan into it and commits it;
# extends the Turing Claude profiles to 2026-11-17 in your factory agents.yaml (backup kept); then validates and locks both plans.
[CmdletBinding(SupportsShouldProcess)]
param([string]$Portfolio = "$HOME\portfolio", [string]$Until = "2026-11-17")
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$platform = Join-Path $Portfolio 'airflow-platform'
$governor = Join-Path $Portfolio 'governor'
$worktree = Join-Path $Portfolio 'governor-airflow'

# 1. this repo
Set-Location $platform
if (-not (Test-Path .git)) {
  git init -b main | Out-Null
  git add -A
  git commit -m "spec, plan, prompts and acceptance for S0-S10" | Out-Null
  Write-Host "airflow-platform: first commit done"
}

# 2. governor worktree (your uncommitted governor changes stay where they are)
if (-not (Test-Path $worktree)) {
  git -C $governor worktree add $worktree -b airflow-integration main
}
$src = Join-Path $platform 'integrations\governor-a1'
Copy-Item (Join-Path $src 'plan-airflow.yaml') $worktree -Force
New-Item -ItemType Directory -Force (Join-Path $worktree 'plan\prompts'), (Join-Path $worktree 'plan\accept') | Out-Null
Copy-Item (Join-Path $src 'plan\prompts\A1.md') (Join-Path $worktree 'plan\prompts\A1.md') -Force
Copy-Item (Join-Path $src 'plan\accept\accept_a1.py') (Join-Path $worktree 'plan\accept\accept_a1.py') -Force
git -C $worktree add plan-airflow.yaml plan/prompts/A1.md plan/accept/accept_a1.py
git -C $worktree commit -m "plan: A1 airflow integration" | Out-Null
Write-Host "governor-airflow: worktree ready on branch airflow-integration"

# 3. factory profiles: Turing Claude account (Opus + Fable) usable until $Until
$agents = Join-Path $HOME '.factory\agents.yaml'
if (Test-Path $agents) {
  Copy-Item $agents "$agents.bak-$(Get-Date -Format yyyyMMddHHmm)"
  $text = Get-Content $agents -Raw
  $new = [regex]::Replace($text, '(?m)^(\s*claude-tc-[a-z]+:.*active_until:\s*)\d{4}-\d{2}-\d{2}', "`${1}$Until")
  Set-Content $agents $new -NoNewline
  Write-Host "agents.yaml: claude-tc-* active_until -> $Until (backup kept)"
}

# 4. validate + lock both plans, show who is available
Set-Location $platform
factory plan validate plan.yaml
factory lock
Set-Location $worktree
factory plan validate plan-airflow.yaml
factory lock --plan plan-airflow.yaml
factory profiles
Write-Host "`nReady. Start with:  cd $platform ; factory run --until-gate"
