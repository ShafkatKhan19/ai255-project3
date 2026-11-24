<#
One-time setup, run by a person on their own PC. After this, everything
is done by the pipeline.

  .\scripts\bootstrap.ps1 -ProjectId YOUR_PROJECT_ID -DnsZone YOUR_ZONE -Domain snip.example.com

What it does:
  1. terraform apply in infra\bootstrap: turns on the APIs, creates the
     bucket for Terraform state, and creates the identity GitHub Actions
     uses (no key file).
  2. Saves seven values as GitHub repository variables, which is how the
     workflows know which project to deploy to. None of them is a secret.

Needs: terraform, the gcloud CLI signed in as an owner of the project
(gcloud auth application-default login), and the gh CLI signed in.
It is safe to run again.
#>
param(
    [Parameter(Mandatory = $true)][string]$ProjectId,
    [Parameter(Mandatory = $true)][string]$DnsZone,
    [Parameter(Mandatory = $true)][string]$Domain,
    [string]$Repository = "ShafkatKhan19/ai255-project3",
    [string]$Region = "us-central1",
    [switch]$AutoApprove
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Folder = Join-Path (Join-Path $Root "infra") "bootstrap"

function Check($what) {
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)" }
}

$env:TF_VAR_project_id = $ProjectId
$env:TF_VAR_region = $Region
$env:TF_VAR_github_repository = $Repository

terraform "-chdir=$Folder" init -input=false
Check "terraform init"
if ($AutoApprove) {
    terraform "-chdir=$Folder" apply -input=false -auto-approve
} else {
    terraform "-chdir=$Folder" apply -input=false
}
Check "terraform apply"

$values = @{
    GCP_PROJECT_ID  = $ProjectId
    GCP_REGION      = $Region
    DNS_ZONE        = $DnsZone
    DOMAIN          = $Domain
    TF_STATE_BUCKET = (terraform "-chdir=$Folder" output -raw state_bucket)
    WIF_PROVIDER    = (terraform "-chdir=$Folder" output -raw workload_identity_provider)
    DEPLOYER_SA     = (terraform "-chdir=$Folder" output -raw deployer_service_account)
}
foreach ($name in $values.Keys) {
    gh variable set $name --repo $Repository --body $values[$name]
    Check "gh variable set $name"
    Write-Host "$name = $($values[$name])"
}
Write-Host ""
Write-Host "Done. Push to main, or run the deploy workflow, to build the environment." -ForegroundColor Green
