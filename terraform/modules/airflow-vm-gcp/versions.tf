terraform {
  # Pinned to the Terraform minor used by the acceptance (stack/versions.yaml); 1.7+ is needed for mock_provider.
  required_version = "~> 1.13.0"

  required_providers {
    google = {
      source = "hashicorp/google"
      # 7.x has scheduling.max_run_duration and instance_termination_action on google_compute_instance in the
      # GA provider (not only google-beta); `terraform validate` against the locked version proves it.
      version = "~> 7.0"
    }
  }
}
