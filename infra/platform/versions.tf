terraform {
  required_version = ">= 1.9"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }

  # State lives in the bucket made by infra/bootstrap. The bucket name is
  # passed at init time (-backend-config="bucket=...") so no project name
  # is fixed in the code. The backend also locks the state, so two
  # pipeline runs can never apply at the same time.
  backend "gcs" {
    prefix = "platform"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

data "google_project" "this" {}
