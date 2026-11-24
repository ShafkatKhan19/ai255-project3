<#
Used once, on 24 Nov 2026 (see the report, Section 3). Kept as a record.

Project 2's environment was built by hand-run scripts (deploy.ps1). This
deletes that environment so the pipeline can build it again from code
with nothing left over from the manual version. After this script the
environment has only ever been created by Terraform and the pipeline.

  .\scripts\retire_project2.ps1 -ProjectId YOUR_PROJECT_ID -DnsZone YOUR_ZONE -Domain snip.example.com -Yes

It deletes the Firestore database and all the links stored in it.
#>
param(
    [Parameter(Mandatory = $true)][string]$ProjectId,
    [Parameter(Mandatory = $true)][string]$DnsZone,
    [Parameter(Mandatory = $true)][string]$Domain,
    [string]$Region = "us-central1",
    [switch]$Yes
)

if (-not $Yes) {
    Write-Host "This deletes the hand-built Project 2 environment, including its data. Add -Yes to go ahead."
    exit 1
}

function Step($text) { Write-Host ""; Write-Host "== $text" -ForegroundColor Cyan }

# Every step may find nothing to delete, so failures do not stop the script.
$ErrorActionPreference = "Continue"

Step "Application and load balancers (delete the namespace first)"
gcloud container clusters get-credentials snip --region=$Region --project=$ProjectId
kubectl delete namespace snip --ignore-not-found --timeout=900s

Step "Cluster"
gcloud container clusters delete snip --region=$Region --project=$ProjectId --quiet

Step "DNS record and reserved address"
gcloud dns record-sets delete "$Domain." --zone=$DnsZone --type=A --project=$ProjectId
gcloud compute addresses delete snip-ip --global --project=$ProjectId --quiet

Step "Image repository"
gcloud artifacts repositories delete snip --location=$Region --project=$ProjectId --quiet

Step "Firestore database"
gcloud firestore databases delete --database="(default)" --project=$ProjectId --quiet

Step "IAM binding for the data services"
$number = gcloud projects describe $ProjectId --format="value(projectNumber)"
$member = "principal://iam.googleapis.com/projects/${number}/locations/global/workloadIdentityPools/${ProjectId}.svc.id.goog/subject/ns/snip/sa/snip-data"
gcloud projects remove-iam-policy-binding $ProjectId --member=$member --role=roles/datastore.user --condition=None --format="value(etag)"

Write-Host ""
Write-Host "Done. Check with: bash scripts/verify_destroyed.sh $ProjectId $DnsZone $Domain" -ForegroundColor Green
exit 0
