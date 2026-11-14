variable "name" {
  description = "Name of the deployment: instance Name tag, resource name prefix, secret slot prefix and ECR repo name."
  type        = string
  default     = "airflow-platform"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,30}[a-z0-9]$", var.name))
    error_message = "name must be 3-32 lowercase letters, digits or hyphens (it is also the ECR repository name)."
  }
}

variable "instance_type" {
  description = "EC2 instance type. Only types with at least 4 GiB of memory are allowed (the idle stack uses about 1.2 GB)."
  type        = string
  default     = "t3.medium"

  validation {
    condition = contains([
      "t3.medium", "t3.large", "t3.xlarge", "t3.2xlarge",
      "t3a.medium", "t3a.large", "t3a.xlarge", "t3a.2xlarge",
      "m5.large", "m5.xlarge", "m6i.large", "m6i.xlarge", "m7i.large", "m7i.xlarge",
    ], var.instance_type)
    error_message = "instance_type must be an x86_64 type with at least 4 GiB of memory from the allowlist in variables.tf."
  }
}

variable "subnet_id" {
  description = "Subnet for the instance. null means a default subnet of the region's default VPC."
  type        = string
  default     = null
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
# Secrets Manager slot "<name>/<KEY>"; you set its value by hand (console or CLI), never through Terraform.
#   AIRFLOW__API_AUTH__JWT_SECRET  signs the API and execution-API tokens (compose falls back to a fixed string)
#   FERNET_KEY                     encrypts connections and variables in the metadata DB (empty locally)
#   _AIRFLOW_WWW_USER_PASSWORD     the FAB admin password that airflow-init creates (airflow locally)
# A slot without a value is skipped at boot and the stack keeps its local default for that key.
variable "secret_names" {
  description = "stack/.env keys whose values are read from Secrets Manager at boot."
  type        = list(string)
  default     = ["AIRFLOW__API_AUTH__JWT_SECRET", "FERNET_KEY", "_AIRFLOW_WWW_USER_PASSWORD"]

  validation {
    condition     = length(var.secret_names) > 0 && alltrue([for n in var.secret_names : can(regex("^[A-Z_][A-Z0-9_]*$", n))])
    error_message = "secret_names must be a non-empty list of env keys (A-Z, 0-9, _)."
  }
}

variable "secret_recovery_window_days" {
  description = "Recovery window of the secret slots on destroy: 0 (delete now, for smoke tests) or 7-30."
  type        = number
  default     = 7

  validation {
    condition     = var.secret_recovery_window_days == 0 || (var.secret_recovery_window_days >= 7 && var.secret_recovery_window_days <= 30)
    error_message = "secret_recovery_window_days must be 0 or between 7 and 30."
  }
}

variable "ttl_minutes" {
  description = "When > 0, the VM shuts down this many minutes after boot and is then terminated. 0 means no TTL."
  type        = number
  default     = 0

  validation {
    condition     = var.ttl_minutes >= 0 && floor(var.ttl_minutes) == var.ttl_minutes
    error_message = "ttl_minutes must be a whole number >= 0."
  }
}

variable "enable_registry" {
  description = "Create a private ECR repository for workload images."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Extra tags for every resource."
  type        = map(string)
  default     = {}
}
