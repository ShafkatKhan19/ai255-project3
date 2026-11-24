variable "project_id" {
  description = "Google Cloud project ID."
  type        = string
}

variable "region" {
  description = "Region for the state bucket."
  type        = string
  default     = "us-central1"
}

variable "github_repository" {
  description = "The one GitHub repository allowed to deploy, as OWNER/NAME."
  type        = string

  validation {
    condition     = can(regex("^[^/]+/[^/]+$", var.github_repository))
    error_message = "Use the form OWNER/NAME, for example ShafkatKhan19/ai255-project3."
  }
}
