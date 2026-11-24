variable "project_id" {
  description = "Google Cloud project ID."
  type        = string
}

variable "region" {
  description = "Region for the cluster, the network and the image repository."
  type        = string
  default     = "us-central1"
}

variable "name" {
  description = "Name given to the cluster, network, repository and address."
  type        = string
  default     = "snip"
}

variable "namespace" {
  description = "Kubernetes namespace the services run in (must match k8s/namespace.yaml)."
  type        = string
  default     = "snip"
}

variable "firestore_location" {
  description = "Firestore location. nam5 is the United States multi-region."
  type        = string
  default     = "nam5"
}

variable "dns_zone" {
  description = "Name of the existing Cloud DNS zone (created in Project 1) that the site's record goes in."
  type        = string
}

variable "domain" {
  description = "Full name the site is served on, for example snip.cloud.example.com. Must be inside dns_zone."
  type        = string

  validation {
    condition     = !endswith(var.domain, ".")
    error_message = "Write the domain without a trailing dot."
  }
}
