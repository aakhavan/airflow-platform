output "instance_name" {
  description = "Name of the Compute Engine instance."
  value       = google_compute_instance.this.name
}

output "zone" {
  description = "Zone of the instance."
  value       = google_compute_instance.this.zone
}

output "tunnel_command" {
  description = "IAP TCP tunnel from localhost:8080 to the Airflow UI on the VM (what scripts/tunnel.ps1 runs)."
  value = join(" ", [
    "gcloud compute start-iap-tunnel ${google_compute_instance.this.name} 8080",
    "--local-host-port=localhost:8080",
    "--zone ${var.zone}",
    "--project ${var.project_id}",
  ])
}

output "secret_names" {
  description = "stack/.env key -> Secret Manager secret ID. Add each value by hand; Terraform creates no versions."
  value       = local.secret_slots
}

output "service_account_email" {
  description = "Email of the VM's service account."
  value       = google_service_account.this.email
}

output "artifact_registry_url" {
  description = "Docker host/path of the Artifact Registry repository, or null when enable_registry is false."
  value       = var.enable_registry ? "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.this[0].repository_id}" : null
}
