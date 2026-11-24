# The pipeline reads these to know where to push images and what to deploy to.

output "registry" {
  description = "Prefix for image names: REGISTRY/web:TAG"
  value       = "${google_artifact_registry_repository.snip.location}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.snip.repository_id}"
}

output "cluster_name" {
  value = google_container_cluster.snip.name
}

output "cluster_location" {
  value = google_container_cluster.snip.location
}

output "https_address" {
  value = google_compute_global_address.snip.address
}

output "url" {
  value = "https://${var.domain}"
}
