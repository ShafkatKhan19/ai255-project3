# GKE Autopilot: Google runs the nodes, and the bill is for what the pods
# request. Same choice as Project 2.

resource "google_container_cluster" "snip" {
  name     = var.name
  location = var.region # regional: control plane and nodes in three zones

  enable_autopilot = true

  network    = google_compute_network.snip.id
  subnetwork = google_compute_subnetwork.snip.id
  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }

  release_channel {
    channel = "REGULAR"
  }

  # Nodes run as a service account made for them (iam.tf), not as the
  # project's default account, which can do far more than a node needs.
  cluster_autoscaling {
    auto_provisioning_defaults {
      service_account = google_service_account.nodes.email
      oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
    }
  }

  # The whole point of this project is that the environment can be
  # destroyed and rebuilt, so Terraform must be allowed to delete it.
  deletion_protection = false

  depends_on = [
    google_project_iam_member.nodes,
    google_artifact_registry_repository_iam_member.nodes_pull,
  ]
}
