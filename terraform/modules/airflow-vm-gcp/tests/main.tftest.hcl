# Offline plan tests with a mocked Google provider: no credentials, no API calls (docs/spec.md §9 rules).

mock_provider "google" {
  mock_resource "google_service_account" {
    defaults = {
      email = "airflow-platform@example-project.iam.gserviceaccount.com"
    }
  }
}

variables {
  project_id = "example-project"
  repo_url   = "https://github.com/example/airflow-platform.git"
  repo_ref   = "main"
}

run "defaults" {
  command = plan

  # Rule: no ingress from 0.0.0.0/0; the only source is the IAP range, on 22 and 8080, to the VM's tag.
  assert {
    condition     = !contains(google_compute_firewall.iap.source_ranges, "0.0.0.0/0")
    error_message = "No ingress from 0.0.0.0/0."
  }

  assert {
    condition     = toset(google_compute_firewall.iap.source_ranges) == toset(["35.235.240.0/20"])
    error_message = "The firewall must allow the IAP range 35.235.240.0/20 only."
  }

  assert {
    condition = (
      google_compute_firewall.iap.direction == "INGRESS" &&
      length(google_compute_firewall.iap.allow) == 1 &&
      one(google_compute_firewall.iap.allow).protocol == "tcp" &&
      toset(one(google_compute_firewall.iap.allow).ports) == toset(["22", "8080"]) &&
      length(google_compute_firewall.iap.deny) == 0
    )
    error_message = "The IAP rule allows tcp 22 and 8080 only."
  }

  assert {
    condition     = toset(google_compute_firewall.iap.target_tags) == toset(google_compute_instance.this.tags) && contains(google_compute_instance.this.tags, "airflow-platform")
    error_message = "The IAP rule targets the instance's tag."
  }

  # No external IP: the network interface has no public address block; egress goes through Cloud NAT.
  assert {
    condition     = length(google_compute_instance.this.network_interface[0].access_config) == 0 && length(google_compute_instance.this.network_interface[0].ipv6_access_config) == 0
    error_message = "The instance must have no external IP."
  }

  assert {
    condition     = length(google_compute_router_nat.this) == 1 && google_compute_router_nat.this[0].region == "europe-west3"
    error_message = "A Cloud NAT gives the VM egress by default."
  }

  # Rule: instance memory >= 4 GB (by type allowlist).
  assert {
    condition = contains([
      "e2-medium", "e2-standard-2", "e2-standard-4", "e2-highmem-2", "e2-highmem-4",
      "n2-standard-2", "n2-standard-4", "n2d-standard-2", "n2d-standard-4", "n4-standard-2", "n4-standard-4",
    ], google_compute_instance.this.machine_type)
    error_message = "The machine type must have at least 4 GB of memory."
  }

  # Rule: no TTL when ttl_minutes = 0.
  assert {
    condition     = length(local.ttl_scheduling) == 0
    error_message = "Without a TTL there is no scheduling block."
  }

  assert {
    condition     = !strcontains(local.user_data, "shutdown -h")
    error_message = "Without a TTL cloud-init must not schedule a shutdown."
  }

  # Rule: the registry is absent when enable_registry = false.
  assert {
    condition     = length(google_artifact_registry_repository.this) == 0 && length(google_artifact_registry_repository_iam_member.reader) == 0
    error_message = "No Artifact Registry repository (or reader binding) without enable_registry."
  }

  # Rule: secret slots have no versions. The module defines no google_secret_manager_secret_version
  # (tests/test_terraform.py checks the source); here: one empty slot per name, under the prefix.
  assert {
    condition     = length(google_secret_manager_secret.slot) == length(var.secret_names)
    error_message = "One secret slot per secret name."
  }

  assert {
    condition     = alltrue([for k, s in google_secret_manager_secret.slot : s.secret_id == "airflow-platform-${k}"])
    error_message = "Slots are named airflow-platform-<KEY>."
  }

  # secretAccessor per slot, for the module's service account only.
  assert {
    condition = alltrue([for k, m in google_secret_manager_secret_iam_member.accessor :
      m.role == "roles/secretmanager.secretAccessor" && m.secret_id == "airflow-platform-${k}"
    ]) && length(google_secret_manager_secret_iam_member.accessor) == length(var.secret_names)
    error_message = "Each slot (and only those) grants secretAccessor."
  }

  assert {
    condition     = strcontains(local.user_data, "SECRET_PREFIX=\"airflow-platform\"") && alltrue([for k in var.secret_names : strcontains(local.user_data, k)])
    error_message = "cloud-init must know every slot name."
  }

  # Spec §9 compute details.
  assert {
    condition = (
      google_compute_instance.this.boot_disk[0].initialize_params[0].image == "ubuntu-os-cloud/ubuntu-2404-lts-amd64" &&
      google_compute_instance.this.boot_disk[0].initialize_params[0].type == "pd-balanced" &&
      google_compute_instance.this.boot_disk[0].initialize_params[0].size == 30
    )
    error_message = "Boot disk must be Ubuntu 24.04 LTS, pd-balanced, 30 GB."
  }

  assert {
    condition = (
      google_compute_instance.this.shielded_instance_config[0].enable_secure_boot &&
      google_compute_instance.this.shielded_instance_config[0].enable_vtpm &&
      google_compute_instance.this.shielded_instance_config[0].enable_integrity_monitoring
    )
    error_message = "The instance must be a Shielded VM."
  }

  assert {
    condition     = google_compute_instance.this.machine_type == "e2-medium" && google_compute_instance.this.zone == "europe-west3-a"
    error_message = "Defaults are e2-medium in europe-west3-a."
  }

  assert {
    condition     = strcontains(local.user_data, "up --projects projects/ci.yaml") && strcontains(local.user_data, "CLOUD=\"gcp\"")
    error_message = "cloud-init must start the stack with the GCP branch."
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
    condition = (
      length(google_compute_instance.this.scheduling) == 1 &&
      google_compute_instance.this.scheduling[0].instance_termination_action == "DELETE" &&
      google_compute_instance.this.scheduling[0].provisioning_model == "STANDARD" &&
      google_compute_instance.this.scheduling[0].max_run_duration[0].seconds == 5400
    )
    error_message = "With a TTL Compute Engine deletes the VM after 90 minutes."
  }

  assert {
    condition     = strcontains(local.user_data, "shutdown -h +90")
    error_message = "cloud-init must schedule shutdown -h +90."
  }

  assert {
    condition     = length(google_artifact_registry_repository.this) == 1 && google_artifact_registry_repository.this[0].repository_id == "airflow-platform"
    error_message = "enable_registry = true creates one Artifact Registry repository."
  }

  assert {
    condition     = length(google_artifact_registry_repository_iam_member.reader) == 1 && google_artifact_registry_repository_iam_member.reader[0].role == "roles/artifactregistry.reader"
    error_message = "enable_registry = true lets the service account read it."
  }

  assert {
    condition     = length(google_compute_instance.this.network_interface[0].access_config) == 0 && toset(google_compute_firewall.iap.source_ranges) == toset(["35.235.240.0/20"])
    error_message = "No external IP and IAP-only ingress hold with a TTL too."
  }
}

run "no_nat" {
  command = plan

  variables {
    create_nat = false
  }

  assert {
    condition     = length(google_compute_router.this) == 0 && length(google_compute_router_nat.this) == 0
    error_message = "create_nat = false creates no router or NAT."
  }
}

run "rejects_small_machine" {
  command = plan

  variables {
    machine_type = "e2-small"
  }

  expect_failures = [var.machine_type]
}
