output "instance_id" {
  description = "ID of the EC2 instance."
  value       = module.airflow_vm.instance_id
}

output "tunnel_command" {
  description = "SSM port-forward to localhost:8080."
  value       = module.airflow_vm.tunnel_command
}

output "secret_names" {
  description = "stack/.env key -> Secrets Manager slot to fill by hand."
  value       = module.airflow_vm.secret_names
}

output "ecr_repository_url" {
  description = "ECR repository URL, or null."
  value       = module.airflow_vm.ecr_repository_url
}
