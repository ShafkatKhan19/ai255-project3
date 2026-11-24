# Where the pipeline pushes the three images.

resource "google_artifact_registry_repository" "snip" {
  repository_id = var.name
  location      = var.region
  format        = "DOCKER"
  description   = "Snip container images"

  # Every commit pushes three new images. Keep the newest ten of each and
  # delete the rest, so storage does not grow for ever.
  cleanup_policies {
    id     = "keep-newest-ten"
    action = "KEEP"
    most_recent_versions {
      keep_count = 10
    }
  }
  cleanup_policies {
    id     = "delete-the-rest"
    action = "DELETE"
    condition {
      older_than = "7d"
    }
  }
}

# The nodes may pull from this repository, and only this one.
resource "google_artifact_registry_repository_iam_member" "nodes_pull" {
  repository = google_artifact_registry_repository.snip.name
  location   = google_artifact_registry_repository.snip.location
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.nodes.email}"
}
