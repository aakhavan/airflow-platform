# Offline plan tests with a mocked AWS provider: no credentials, no API calls (docs/spec.md §9 rules).

mock_provider "aws" {
  override_data {
    target = data.aws_ssm_parameter.ubuntu
    values = {
      insecure_value = "ami-0123456789abcdef0"
      value          = "ami-0123456789abcdef0"
    }
  }

  override_data {
    target = data.aws_vpc.default
    values = {
      id      = "vpc-0123456789abcdef0"
      default = true
    }
  }

  override_data {
    target = data.aws_region.current
    values = {
      region = "eu-central-1"
    }
  }

  override_data {
    target = data.aws_partition.current
    values = {
      partition = "aws"
    }
  }
}

variables {
  repo_url = "https://github.com/example/airflow-platform.git"
  repo_ref = "main"
}

run "defaults" {
  command = plan

  # Rule: no ingress from 0.0.0.0/0 (no ingress at all).
  assert {
    condition     = length(aws_security_group.this.ingress) == 0
    error_message = "The security group must have no ingress rules."
  }

  assert {
    condition     = alltrue([for r in aws_security_group.this.ingress : !contains(r.cidr_blocks, "0.0.0.0/0")])
    error_message = "No ingress from 0.0.0.0/0."
  }

  # Rule: instance memory >= 4 GiB (by type allowlist).
  assert {
    condition = contains([
      "t3.medium", "t3.large", "t3.xlarge", "t3.2xlarge",
      "t3a.medium", "t3a.large", "t3a.xlarge", "t3a.2xlarge",
      "m5.large", "m5.xlarge", "m6i.large", "m6i.xlarge", "m7i.large", "m7i.xlarge",
    ], aws_instance.this.instance_type)
    error_message = "The instance type must have at least 4 GiB of memory."
  }

  # Rule: no TTL when ttl_minutes = 0.
  assert {
    condition     = aws_instance.this.instance_initiated_shutdown_behavior == "stop"
    error_message = "Without a TTL a shutdown must only stop the instance."
  }

  assert {
    condition     = !strcontains(local.user_data, "shutdown -h")
    error_message = "Without a TTL cloud-init must not schedule a shutdown."
  }

  # Rule: the registry is absent when enable_registry = false.
  assert {
    condition     = length(aws_ecr_repository.this) == 0 && length(aws_iam_role_policy.pull_registry) == 0
    error_message = "No ECR repository (or pull policy) without enable_registry."
  }

  # Rule: secret slots have no versions. The module defines no aws_secretsmanager_secret_version
  # (tests/test_terraform.py checks the source); here: one empty slot per name, under the prefix.
  assert {
    condition     = length(aws_secretsmanager_secret.slot) == length(var.secret_names)
    error_message = "One secret slot per secret name."
  }

  assert {
    condition     = alltrue([for k, s in aws_secretsmanager_secret.slot : s.name == "airflow-platform/${k}"])
    error_message = "Slots are named airflow-platform/<KEY>."
  }

  assert {
    condition     = alltrue([for k in var.secret_names : strcontains(local.user_data, k)]) && strcontains(local.user_data, "SECRET_PREFIX=\"airflow-platform\"")
    error_message = "cloud-init must know every slot name."
  }

  # Rule: IMDSv2 is required.
  assert {
    condition     = aws_instance.this.metadata_options[0].http_tokens == "required"
    error_message = "IMDSv2 must be required."
  }

  # Spec §9 compute details.
  assert {
    condition     = aws_instance.this.ami == "ami-0123456789abcdef0"
    error_message = "The AMI comes from the Ubuntu 24.04 SSM public parameter."
  }

  assert {
    condition     = data.aws_ssm_parameter.ubuntu.name == "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
    error_message = "The AMI parameter must be Ubuntu 24.04 LTS."
  }

  assert {
    condition = (
      aws_instance.this.root_block_device[0].volume_type == "gp3" &&
      aws_instance.this.root_block_device[0].volume_size == 30 &&
      aws_instance.this.root_block_device[0].encrypted == true
    )
    error_message = "Root volume must be gp3, 30 GB, encrypted."
  }

  assert {
    condition     = aws_security_group.this.vpc_id == "vpc-0123456789abcdef0"
    error_message = "With subnet_id = null the default VPC is used."
  }

  assert {
    condition     = aws_iam_role_policy_attachment.ssm_core.policy_arn == "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
    error_message = "The role must have AmazonSSMManagedInstanceCore."
  }

  assert {
    condition     = strcontains(local.user_data, "up --projects projects/ci.yaml") && strcontains(local.user_data, "CLOUD=\"aws\"")
    error_message = "cloud-init must start the stack with the AWS branch."
  }
}

run "ttl_and_registry" {
  command = plan

  variables {
    ttl_minutes     = 90
    enable_registry = true
  }

  # Rule: the TTL is set when ttl_minutes > 0.
  assert {
    condition     = aws_instance.this.instance_initiated_shutdown_behavior == "terminate"
    error_message = "With a TTL the OS shutdown must terminate the instance."
  }

  assert {
    condition     = strcontains(local.user_data, "shutdown -h +90")
    error_message = "cloud-init must schedule shutdown -h +90."
  }

  assert {
    condition     = length(aws_ecr_repository.this) == 1 && aws_ecr_repository.this[0].name == "airflow-platform"
    error_message = "enable_registry = true creates one ECR repository."
  }

  assert {
    condition     = length(aws_iam_role_policy.pull_registry) == 1
    error_message = "enable_registry = true lets the role pull from it."
  }

  assert {
    condition     = length(aws_security_group.this.ingress) == 0 && aws_instance.this.metadata_options[0].http_tokens == "required"
    error_message = "No ingress and IMDSv2 hold with a TTL too."
  }
}

run "rejects_small_instance" {
  command = plan

  variables {
    instance_type = "t3.small"
  }

  expect_failures = [var.instance_type]
}
