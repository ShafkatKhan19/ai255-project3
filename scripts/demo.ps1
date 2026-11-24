<#
The demonstration: a full teardown and a full rebuild, both run by the
pipeline, timed, with the output saved in evidence\.

  .\scripts\demo.ps1                    teardown, then rebuild
  .\scripts\demo.ps1 -Only teardown     just the teardown
  .\scripts\demo.ps1 -Only rebuild      just the rebuild

Nothing here touches Google Cloud directly. It starts the two GitHub
workflows (destroy, then deploy), waits for them, and then keeps testing
https://DOMAIN until the new certificate is issued.
Needs the gh CLI signed in. Run it from the repository folder.
#>
param(
    [ValidateSet("both", "teardown", "rebuild")][string]$Only = "both",
    [string]$Name = (Get-Date -Format "yyyyMMdd-HHmm"),
    [int]$HttpsMinutes = 90
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Evidence = Join-Path $Root "evidence"
New-Item -ItemType Directory -Force -Path $Evidence | Out-Null
$Summary = Join-Path $Evidence "$Name-summary.txt"

function Note($text) {
    $line = "{0}  {1}" -f (Get-Date -Format "HH:mm:ss"), $text
    Write-Host $line -ForegroundColor Cyan
    Add-Content -Path $Summary -Value $line
}

# Start a workflow, wait for it to finish, save its job timings and log.
function Run($workflow, $label, $extra) {
    $before = (gh run list --workflow $workflow --limit 1 --json databaseId --jq ".[0].databaseId")
    Note "$label started"
    gh workflow run $workflow --ref main @extra
    if ($LASTEXITCODE -ne 0) { throw "could not start $workflow" }
    $id = $before
    for ($i = 0; $i -lt 30 -and $id -eq $before; $i++) {
        Start-Sleep -Seconds 4
        $id = (gh run list --workflow $workflow --limit 1 --json databaseId --jq ".[0].databaseId")
    }
    if ($id -eq $before) { throw "the $workflow run did not appear" }
    gh run watch $id --interval 20 --exit-status | Out-Null
    $ok = ($LASTEXITCODE -eq 0)
    gh run view $id --json jobs --jq '.jobs[] | "\(.name)\t\(.conclusion)\t\(.startedAt)\t\(.completedAt)"' |
        Set-Content (Join-Path $Evidence "$Name-$label-jobs.txt")
    gh run view $id --log | Set-Content (Join-Path $Evidence "$Name-$label-log.txt")
    $run = gh run view $id --json createdAt,updatedAt,url | ConvertFrom-Json
    $minutes = [math]::Round(((Get-Date $run.updatedAt) - (Get-Date $run.createdAt)).TotalMinutes, 1)
    Note "$label finished: $(if ($ok) { 'success' } else { 'FAILED' }) in $minutes minutes  $($run.url)"
    if (-not $ok) { throw "$label failed; see $($run.url)" }
}

if ($Only -ne "rebuild") {
    Run "destroy.yml" "teardown" @("-f", "confirm=destroy")
}
if ($Only -ne "teardown") {
    Run "deploy.yml" "rebuild" @()

    $domain = (gh variable get DOMAIN)
    Note "waiting for the certificate: testing https://$domain every minute"
    $started = Get-Date
    $passed = $false
    while (((Get-Date) - $started).TotalMinutes -lt $HttpsMinutes) {
        py (Join-Path $PSScriptRoot "smoke_test.py") "https://$domain" 2>&1 |
            Set-Content (Join-Path $Evidence "$Name-https-smoke.txt")
        if ($LASTEXITCODE -eq 0) { $passed = $true; break }
        Start-Sleep -Seconds 60
    }
    $waited = [math]::Round(((Get-Date) - $started).TotalMinutes, 1)
    if ($passed) { Note "HTTPS passed every check $waited minutes after the pipeline finished" }
    else { Note "HTTPS still not passing after $waited minutes" }
}
Write-Host ""
Get-Content $Summary
