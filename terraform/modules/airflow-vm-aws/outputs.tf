output "instance_id" {
  description = "ID of the EC2 instance."
  value       = aws_instance.this.id
}

output "tunnel_command" {
  description = "SSM port-forward from localhost:8080 to the Airflow UI on the VM (what scripts/tunnel.ps1 runs)."
  value = join(" ", [
    "aws ssm start-session",
    "--region ${data.aws_region.current.region}",
    "--target ${aws_instance.this.id}",
    "--document-name AWS-StartPortForwardingSession",
    "--parameters portNumber=8080,localPortNumber=8080",
  ])
}

output "secret_names" {
  description = "stack/.env key -> Secrets Manager slot name. Set each value by hand; Terraform creates no versions."
  value       = local.secret_slots
}

output "security_group_id" {
  description = "The security group (no ingress)."
  value       = aws_security_group.this.id
}

output "ecr_repository_url" {
  description = "URL of the ECR repository, or null when enable_registry is false."
  value       = var.enable_registry ? aws_ecr_repository.this[0].repository_url : null
}
