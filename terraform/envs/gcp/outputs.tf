output "instance_name" {
  description = "Name of the Compute Engine instance."
  value       = module.airflow_vm.instance_name
}

output "zone" {
  description = "Zone of the instance."
  value       = module.airflow_vm.zone
}

output "tunnel_command" {
  description = "IAP tunnel to localhost:8080."
  value       = module.airflow_vm.tunnel_command
}

output "secret_names" {
  description = "stack/.env key -> Secret Manager secret to fill by hand."
  value       = module.airflow_vm.secret_names
}

output "artifact_registry_url" {
  description = "Artifact Registry repository path, or null."
  value       = module.airflow_vm.artifact_registry_url
}
