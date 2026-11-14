terraform {
  # Pinned to the Terraform minor used by the acceptance (stack/versions.yaml); 1.7+ is needed for mock_provider.
  required_version = "~> 1.13.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
