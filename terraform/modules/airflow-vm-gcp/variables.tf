variable "project_id" {
  description = "GCP project that holds every resource of this module."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a GCP project ID (6-30 lowercase letters, digits or hyphens)."
  }
}

variable "region" {
  description = "Region of the Cloud Router/NAT and the Artifact Registry repository."
  type        = string
  default     = "europe-west3"
}

variable "zone" {
  description = "Zone of the VM (must be in region)."
  type        = string
  default     = "europe-west3-a"

  validation {
    condition     = can(regex("^[a-z]+-[a-z]+[0-9]+-[a-z]$", var.zone))
    error_message = "zone must look like europe-west3-a."
  }
}

variable "name" {
  description = "Name of the deployment: instance name, network tag, service account ID, secret ID prefix and registry ID."
  type        = string
  default     = "airflow-platform"

  validation {
    # 28 chars max so "<name>" fits a service account ID (6-30) and "<name>-nat"-style names stay valid.
    condition     = can(regex("^[a-z][a-z0-9-]{4,26}[a-z0-9]$", var.name))
    error_message = "name must be 6-28 lowercase letters, digits or hyphens, starting with a letter."
  }
}

variable "machine_type" {
  description = "Machine type. Only types with at least 4 GB of memory are allowed (the idle stack uses about 1.2 GB)."
  type        = string
  default     = "e2-medium"

  validation {
    condition = contains([
      "e2-medium", "e2-standard-2", "e2-standard-4", "e2-highmem-2", "e2-highmem-4",
      "n2-standard-2", "n2-standard-4", "n2d-standard-2", "n2d-standard-4", "n4-standard-2", "n4-standard-4",
    ], var.machine_type)
    error_message = "machine_type must be an x86_64 type with at least 4 GB of memory from the allowlist in variables.tf."
  }
}

variable "network" {
  description = "VPC network of the VM, the IAP firewall rule and the Cloud NAT."
  type        = string
  default     = "default"
}

variable "create_nat" {
  description = "Create a Cloud Router + Cloud NAT for egress (the VM has no external IP). Set false when the network already has one."
  type        = bool
  default     = true
}

variable "repo_url" {
  description = "Git URL of airflow-platform that cloud-init clones (must be readable without credentials)."
  type        = string

  validation {
    condition     = can(regex("^https://[^\\s\"'$`]+$", var.repo_url))
    error_message = "repo_url must be an https URL without quotes, spaces or shell characters."
  }
}

variable "repo_ref" {
  description = "Branch, tag or commit that cloud-init checks out."
  type        = string
  default     = "main"

  validation {
    condition     = can(regex("^[A-Za-z0-9._/-]+$", var.repo_ref))
    error_message = "repo_ref may contain only letters, digits, '.', '_', '/' and '-'."
  }
}

# The keys of stack/.env that must not keep their local defaults on a VM. Each one gets an empty
# Secret Manager secret "<name>-<KEY>" (IDs cannot contain '/'); you add its version by hand, never through Terraform.
# A secret without a version is skipped at boot and the stack keeps its local default for that key.
variable "secret_names" {
  description = "stack/.env keys whose values are read from Secret Manager at boot."
  type        = list(string)
  default     = ["AIRFLOW__API_AUTH__JWT_SECRET", "FERNET_KEY", "_AIRFLOW_WWW_USER_PASSWORD"]

  validation {
    condition     = length(var.secret_names) > 0 && alltrue([for n in var.secret_names : can(regex("^[A-Z_][A-Z0-9_]*$", n))])
    error_message = "secret_names must be a non-empty list of env keys (A-Z, 0-9, _)."
  }
}

variable "ttl_minutes" {
  description = "When > 0, Compute Engine deletes the VM this many minutes after it starts (max_run_duration). 0 means no TTL."
  type        = number
  default     = 0

  validation {
    condition     = var.ttl_minutes >= 0 && floor(var.ttl_minutes) == var.ttl_minutes
    error_message = "ttl_minutes must be a whole number >= 0."
  }
}

variable "enable_registry" {
  description = "Create a private Artifact Registry Docker repository for workload images."
  type        = bool
  default     = false
}

variable "labels" {
  description = "Extra labels for every resource that takes labels (lowercase keys and values)."
  type        = map(string)
  default     = {}
}
