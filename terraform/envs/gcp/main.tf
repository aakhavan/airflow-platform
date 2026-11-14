# GCP environment: one airflow-platform VM. Local state by default; scripts/remote-state.ps1 (S9)
# adds the remote state file when it is used. Credentials come from your own gcloud login (ADC).
# The project needs the compute, secretmanager, iap (and artifactregistry) APIs enabled.

terraform {
  required_version = "~> 1.13.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone

  default_labels = merge({ project = "airflow-platform" }, var.labels)
}

module "airflow_vm" {
  source = "../../modules/airflow-vm-gcp"

  project_id      = var.project_id
  region          = var.region
  zone            = var.zone
  name            = var.name
  machine_type    = var.machine_type
  network         = var.network
  create_nat      = var.create_nat
  repo_url        = var.repo_url
  repo_ref        = var.repo_ref
  secret_names    = var.secret_names
  ttl_minutes     = var.ttl_minutes
  enable_registry = var.enable_registry
  labels          = var.labels
}
