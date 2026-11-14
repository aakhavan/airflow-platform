# AWS environment: one airflow-platform VM. Local state by default; scripts/remote-state.ps1 (S9)
# adds the remote state file when it is used. Credentials come from your own aws CLI login.

terraform {
  required_version = "~> 1.13.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = merge({ project = "airflow-platform" }, var.tags)
  }
}

module "airflow_vm" {
  source = "../../modules/airflow-vm-aws"

  name                        = var.name
  instance_type               = var.instance_type
  subnet_id                   = var.subnet_id
  repo_url                    = var.repo_url
  repo_ref                    = var.repo_ref
  secret_names                = var.secret_names
  secret_recovery_window_days = var.secret_recovery_window_days
  ttl_minutes                 = var.ttl_minutes
  enable_registry             = var.enable_registry
  tags                        = var.tags
}
