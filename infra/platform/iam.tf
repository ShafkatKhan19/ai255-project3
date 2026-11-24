# Who may do what. Three identities, each with the least it needs:
#
#   nodes      pull images from one repository; write logs and metrics
#   snip-data  (links and stats pods) read and write Firestore
#   snip-web   (web pods) nothing: it has no entry here at all

resource "google_service_account" "nodes" {
  account_id   = "${var.name}-nodes"
  display_name = "Snip GKE nodes"
}

# The smallest role GKE accepts for nodes (logs, metrics, monitoring).
resource "google_project_iam_member" "nodes" {
  project = var.project_id
  role    = "roles/container.defaultNodeServiceAccount"
  member  = "serviceAccount:${google_service_account.nodes.email}"
}

# Workload Identity: pods running as the Kubernetes service account
# snip-data are treated by Google Cloud as this principal. No key file.
resource "google_project_iam_member" "data_services_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "principal://iam.googleapis.com/projects/${data.google_project.this.number}/locations/global/workloadIdentityPools/${var.project_id}.svc.id.goog/subject/ns/${var.namespace}/sa/snip-data"

  # The identity pool PROJECT.svc.id.goog only exists once the project
  # has a cluster.
  depends_on = [google_container_cluster.snip]
}
