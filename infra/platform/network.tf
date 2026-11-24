# The cluster gets its own network instead of the project's "default" one,
# so a teardown removes every trace and nothing is shared with Project 1.

resource "google_compute_network" "snip" {
  name                    = var.name
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "snip" {
  name          = var.name
  region        = var.region
  network       = google_compute_network.snip.id
  ip_cidr_range = "10.10.0.0/20" # nodes

  # GKE gives every pod and every Service its own address from these.
  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = "10.20.0.0/16"
  }
  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = "10.30.0.0/20"
  }

  private_ip_google_access = true
}
