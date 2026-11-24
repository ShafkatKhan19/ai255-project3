# Checks on the plan, run by `terraform test` in the pipeline before
# anything is applied. The Google provider is replaced by a mock, so these
# need no credentials and create nothing.
#
# Each check guards a decision that the report depends on.

mock_provider "google" {
  mock_data "google_project" {
    defaults = {
      number = "123456789012"
    }
  }
  mock_data "google_dns_managed_zone" {
    defaults = {
      name     = "web-zone"
      dns_name = "cloud.example.com."
    }
  }
}

variables {
  project_id = "test-project"
  dns_zone   = "web-zone"
  domain     = "snip.cloud.example.com"
}

run "environment_can_be_destroyed" {
  command = plan

  assert {
    condition     = google_container_cluster.snip.deletion_protection == false
    error_message = "The cluster must be deletable by terraform destroy."
  }
  assert {
    condition     = google_firestore_database.default.deletion_policy == "DELETE"
    error_message = "The database must be deleted by terraform destroy, not just forgotten."
  }
  assert {
    condition     = google_firestore_database.default.delete_protection_state == "DELETE_PROTECTION_DISABLED"
    error_message = "Delete protection would make terraform destroy fail."
  }
}

run "same_shape_as_project_2" {
  command = plan

  assert {
    condition     = google_container_cluster.snip.enable_autopilot == true
    error_message = "Project 2 ran on GKE Autopilot."
  }
  assert {
    condition     = google_container_cluster.snip.location == "us-central1"
    error_message = "The cluster must be regional in us-central1."
  }
  assert {
    condition     = google_firestore_database.default.name == "(default)" && google_firestore_database.default.type == "FIRESTORE_NATIVE"
    error_message = "The services use the default Firestore database in Native mode."
  }
  assert {
    condition     = google_artifact_registry_repository.snip.format == "DOCKER"
    error_message = "The repository must hold container images."
  }
  assert {
    condition     = google_compute_global_address.snip.name == "snip-ip"
    error_message = "k8s/https.yaml asks for the address by the name snip-ip."
  }
  assert {
    condition     = google_dns_record_set.site.name == "snip.cloud.example.com." && google_dns_record_set.site.type == "A"
    error_message = "The site needs an A record for its full name."
  }
}

run "least_privilege" {
  command = plan

  assert {
    condition     = google_project_iam_member.data_services_firestore.role == "roles/datastore.user"
    error_message = "The data services get Firestore access and nothing more."
  }
  assert {
    condition     = google_project_iam_member.data_services_firestore.member == "principal://iam.googleapis.com/projects/123456789012/locations/global/workloadIdentityPools/test-project.svc.id.goog/subject/ns/snip/sa/snip-data"
    error_message = "Firestore access must go to the Kubernetes service account snip-data in the snip namespace only."
  }
  assert {
    condition     = google_project_iam_member.nodes.role == "roles/container.defaultNodeServiceAccount"
    error_message = "Nodes get the minimal node role."
  }
  assert {
    condition     = google_compute_network.snip.auto_create_subnetworks == false
    error_message = "The network must have only the one subnet declared here."
  }
}

run "domain_is_validated" {
  command = plan

  variables {
    domain = "snip.cloud.example.com."
  }
  expect_failures = [var.domain]
}
