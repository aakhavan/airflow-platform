variable "region" {
  description = "AWS region."
  type        = string
  default     = "eu-central-1"
}

variable "name" {
  description = "Deployment name (see the module)."
  type        = string
  default     = "airflow-platform"
}

variable "instance_type" {
  description = "EC2 instance type (>= 4 GiB memory allowlist in the module)."
  type        = string
  default     = "t3.medium"
}

variable "subnet_id" {
  description = "Subnet; null uses the default VPC."
  type        = string
  default     = null
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
  description = "stack/.env keys read from Secrets Manager at boot (names only; values are set by hand)."
  type        = list(string)
  default     = ["AIRFLOW__API_AUTH__JWT_SECRET", "FERNET_KEY", "_AIRFLOW_WWW_USER_PASSWORD"]
}

variable "secret_recovery_window_days" {
  description = "0 for smoke tests (slots deleted at once on destroy), else 7-30."
  type        = number
  default     = 7
}

variable "ttl_minutes" {
  description = "Minutes until the VM shuts down and is terminated; 0 = no TTL."
  type        = number
  default     = 0
}

variable "enable_registry" {
  description = "Create a private ECR repository."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Extra tags."
  type        = map(string)
  default     = {}
}
