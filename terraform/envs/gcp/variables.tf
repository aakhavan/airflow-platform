variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "GCP region."
  type        = string
  default     = "europe-west3"
}

variable "zone" {
  description = "GCP zone of the VM."
  type        = string
  default     = "europe-west3-a"
}

variable "name" {
  description = "Deployment name (see the module)."
  type        = string
  default     = "airflow-platform"
}

variable "machine_type" {
  description = "Machine type (>= 4 GB memory allowlist in the module)."
  type        = string
  default     = "e2-medium"
}

variable "network" {
  description = "VPC network."
  type        = string
  default     = "default"
}

variable "create_nat" {
  description = "Create a Cloud Router + NAT for egress; false when the network already has one."
  type        = bool
  default     = true
}

variable "repo_url" {
  description = "Git URL of airflow-platform that the VM clones."
  type        = string
}

variable "repo_ref" {
  description = "Branch, tag or commit to deploy."
  type        = string
  default     = "main"
}

variable "secret_names" {
  description = "stack/.env keys read from Secret Manager at boot (names only; values are added by hand)."
  type        = list(string)
  default     = ["AIRFLOW__API_AUTH__JWT_SECRET", "FERNET_KEY", "_AIRFLOW_WWW_USER_PASSWORD"]
}

variable "ttl_minutes" {
  description = "Minutes until Compute Engine deletes the VM; 0 = no TTL."
  type        = number
  default     = 0
}

variable "enable_registry" {
  description = "Create a private Artifact Registry repository."
  type        = bool
  default     = false
}

variable "labels" {
  description = "Extra labels."
  type        = map(string)
  default     = {}
}
