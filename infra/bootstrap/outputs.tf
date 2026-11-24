# scripts/bootstrap.ps1 copies these into the GitHub repository's variables.
# None of them is a secret.

output "state_bucket" {
  value = google_storage_bucket.state.name
}

output "workload_identity_provider" {
  value = google_iam_workload_identity_pool_provider.github.name
}

output "deployer_service_account" {
  value = google_service_account.deployer.email
}

output "project_number" {
  value = data.google_project.this.number
}
