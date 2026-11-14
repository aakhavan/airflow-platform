# One EC2 VM that runs the same compose stack as the laptop (ADR 0002, docs/spec.md §9).
# No ingress at all: access is an SSM port-forward. Secret slots are created empty; values are set by hand.

locals {
  tags = merge({ "airflow-platform" = var.name, "managed-by" = "terraform" }, var.tags)

  # stack/.env key -> Secrets Manager slot name. The cloud-init template builds the same "<prefix>/<KEY>".
  secret_slots = { for key in var.secret_names : key => "${var.name}/${key}" }

  vpc_id = var.subnet_id == null ? data.aws_vpc.default[0].id : data.aws_subnet.selected[0].vpc_id

  user_data = templatefile("${path.module}/../../templates/cloud-init.yaml.tftpl", {
    cloud         = "aws"
    region        = data.aws_region.current.region
    repo_url      = var.repo_url
    repo_ref      = var.repo_ref
    secret_names  = var.secret_names
    secret_prefix = var.name
    ttl_minutes   = var.ttl_minutes
  })
}

data "aws_region" "current" {}

data "aws_partition" "current" {}

# Ubuntu 24.04 LTS (amd64, gp3) from Canonical's SSM public parameter.
data "aws_ssm_parameter" "ubuntu" {
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}

data "aws_vpc" "default" {
  count   = var.subnet_id == null ? 1 : 0
  default = true
}

data "aws_subnet" "selected" {
  count = var.subnet_id == null ? 0 : 1
  id    = var.subnet_id
}

# --- network: no ingress rules, egress all ---------------------------------------------------

resource "aws_security_group" "this" {
  name_prefix = "${var.name}-"
  description = "airflow-platform VM: no ingress, access through SSM only"
  vpc_id      = local.vpc_id
  ingress     = []

  egress {
    description      = "all outbound (apt, docker hub, git, AWS APIs)"
    from_port        = 0
    to_port          = 0
    protocol         = "-1"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  tags = merge(local.tags, { Name = var.name })

  lifecycle {
    create_before_destroy = true
  }
}

# --- secret slots (no versions: values never pass through Terraform or its state) -------------

resource "aws_secretsmanager_secret" "slot" {
  for_each = local.secret_slots

  name                    = each.value
  description             = "airflow-platform ${var.name}: value of stack/.env key ${each.key}, set by hand"
  recovery_window_in_days = var.secret_recovery_window_days
  tags                    = local.tags
}

# --- identity: SSM core + read of its own slots only -----------------------------------------

resource "aws_iam_role" "this" {
  name_prefix = "${var.name}-"
  description = "airflow-platform VM ${var.name}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = local.tags
}

resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.this.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "read_secret_slots" {
  name = "read-own-secret-slots"
  role = aws_iam_role.this.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "ReadOwnSecretSlots"
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = [for s in aws_secretsmanager_secret.slot : s.arn]
    }]
  })
}

resource "aws_iam_instance_profile" "this" {
  name_prefix = "${var.name}-"
  role        = aws_iam_role.this.name
  tags        = local.tags
}

# --- optional registry -----------------------------------------------------------------------

resource "aws_ecr_repository" "this" {
  count = var.enable_registry ? 1 : 0

  name                 = var.name
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = local.tags
}

resource "aws_iam_role_policy" "pull_registry" {
  count = var.enable_registry ? 1 : 0

  name = "pull-own-registry"
  role = aws_iam_role.this.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Sid = "EcrLogin", Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
      {
        Sid      = "PullOwnRepository"
        Effect   = "Allow"
        Action   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"]
        Resource = [aws_ecr_repository.this[0].arn]
      },
    ]
  })
}

# --- the VM ----------------------------------------------------------------------------------

resource "aws_instance" "this" {
  ami                    = data.aws_ssm_parameter.ubuntu.insecure_value
  instance_type          = var.instance_type
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [aws_security_group.this.id]
  iam_instance_profile   = aws_iam_instance_profile.this.name

  # With a TTL, the scheduled OS shutdown terminates the instance; without one, a shutdown only stops it.
  instance_initiated_shutdown_behavior = var.ttl_minutes > 0 ? "terminate" : "stop"

  user_data                   = local.user_data
  user_data_replace_on_change = true

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required" # IMDSv2 only
    # 2 hops so containers on the docker bridge can reach IMDS (the Airflow secrets backend uses the role).
    http_put_response_hop_limit = 2
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = 30
    encrypted             = true
    delete_on_termination = true
  }

  tags        = merge(local.tags, { Name = var.name })
  volume_tags = local.tags

  lifecycle {
    # A newer Ubuntu AMI in the SSM parameter must not replace a running VM; recreate it on purpose.
    ignore_changes = [ami]
  }

  depends_on = [aws_iam_role_policy_attachment.ssm_core, aws_iam_role_policy.read_secret_slots]
}
