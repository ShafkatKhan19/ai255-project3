# Bootstrap: the few things that must exist before the pipeline can run.
#
# A person applies this ONCE from their own machine (scripts/bootstrap.ps1).
# It is the only part of the project that is not built by the pipeline,
# because the pipeline cannot create its own identity or the bucket that
# holds its own state. It is not removed by a teardown.
#
#   1. the Google Cloud APIs the project uses
#   2. a bucket for the Terraform state of infra/platform
#   3. an identity for GitHub Actions, with no key file (Workload Identity
#      Federation), and the roles it needs to build the environment

terraform {
  required_version = ">= 1.9"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }
  # State for this folder stays on the machine that ran it (see the
  # report, Section 9, for why and what that costs).
}

provider "google" {
  project = var.project_id
  region  = var.region
}

data "google_project" "this" {}

# ---------------------------------------------------------------- 1. APIs

resource "google_project_service" "apis" {
  for_each = toset([
    "artifactregistry.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "container.googleapis.com",
    "dns.googleapis.com",
    "firestore.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
  ])
  service = each.value
  # Leave the APIs on if this folder is ever destroyed: Project 1 runs in
  # the same Google Cloud project and uses some of them.
  disable_on_destroy = false
}

# --------------------------------------------------------- 2. State bucket

resource "google_storage_bucket" "state" {
  name     = "${var.project_id}-tfstate"
  location = upper(var.region)

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  # Keep old versions of the state so a bad apply can be undone by hand.
  versioning {
    enabled = true
  }
  lifecycle_rule {
    condition {
      num_newer_versions = 20
    }
    action {
      type = "Delete"
    }
  }
}

# ------------------------------------------------- 3. Pipeline identity

# GitHub Actions proves who it is with a short-lived token signed by
# GitHub. Google checks the token against this pool and provider. No
# service account key exists anywhere.
resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github"
  display_name              = "GitHub Actions"
  depends_on                = [google_project_service.apis]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub Actions"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }
  # Only workflows in this one repository, running on the main branch, are
  # accepted. A pull request or a fork gets no cloud access at all.
  attribute_condition = "assertion.repository == '${var.github_repository}' && assertion.ref == 'refs/heads/main'"
}

resource "google_service_account" "deployer" {
  account_id   = "snip-deployer"
  display_name = "Snip pipeline (GitHub Actions)"
  depends_on   = [google_project_service.apis]
}

resource "google_service_account_iam_member" "github_may_act_as_deployer" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repository}"
}

# What the pipeline may do. Each role is here because a resource in
# infra/platform or a step in the workflows needs it.
locals {
  deployer_roles = {
    "roles/container.admin"         = "create and delete the cluster; kubectl apply"
    "roles/artifactregistry.admin"  = "create and delete the image repository; push images"
    "roles/datastore.owner"         = "create and delete the Firestore database"
    "roles/compute.networkAdmin"    = "the VPC, the subnet and the reserved address"
    "roles/compute.viewer"          = "list leftovers after a teardown"
    "roles/dns.admin"               = "the DNS record for the site"
    "roles/iam.serviceAccountAdmin" = "create and delete the node service account"
    "roles/iam.serviceAccountUser"  = "attach the node service account to the cluster"
  }
}

resource "google_project_iam_member" "deployer" {
  for_each = local.deployer_roles
  project  = var.project_id
  role     = each.key
  member   = "serviceAccount:${google_service_account.deployer.email}"
}

# The pipeline has to grant two roles itself (Firestore access for the
# data services, and the node role for the node service account). Being
# able to change project IAM is powerful, so it is limited by a condition:
# these two roles and nothing else.
resource "google_project_iam_member" "deployer_limited_iam" {
  project = var.project_id
  role    = "roles/resourcemanager.projectIamAdmin"
  member  = "serviceAccount:${google_service_account.deployer.email}"

  condition {
    title       = "only-the-two-roles-snip-needs"
    description = "The pipeline may grant or revoke these roles only."
    expression  = "api.getAttribute('iam.googleapis.com/modifiedGrantsByRole', []).hasOnly(['roles/datastore.user', 'roles/container.defaultNodeServiceAccount'])"
  }
}

# Read and write the Terraform state, in this bucket only.
resource "google_storage_bucket_iam_member" "deployer_state" {
  bucket = google_storage_bucket.state.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.deployer.email}"
}
