# One Compute Engine VM that runs the same compose stack as the laptop (ADR 0002, docs/spec.md §9).
# No public address: access is an IAP TCP tunnel, egress goes through Cloud NAT. Secret slots are created
# empty; versions (values) are added by hand.

locals {
  labels = merge({ "airflow-platform" = var.name, "managed-by" = "terraform" }, var.labels)

  # stack/.env key -> Secret Manager secret ID. The cloud-init template builds the same "<prefix>-<KEY>".
  secret_slots = { for key in var.secret_names : key => "${var.name}-${key}" }

  # Google's published range for IAP TCP forwarding: the only source allowed in.
  iap_source_ranges = ["35.235.240.0/20"]

  # Rendered as the scheduling block only when there is a TTL.
  ttl_scheduling = var.ttl_minutes > 0 ? [var.ttl_minutes * 60] : []

  user_data = templatefile("${path.module}/../../templates/cloud-init.yaml.tftpl", {
    cloud         = "gcp"
    region        = var.region
    repo_url      = var.repo_url
    repo_ref      = var.repo_ref
    secret_names  = var.secret_names
    secret_prefix = var.name
    ttl_minutes   = var.ttl_minutes
  })
}

# --- identity --------------------------------------------------------------------------------

resource "google_service_account" "this" {
  project      = var.project_id
  account_id   = var.name
  display_name = "airflow-platform VM ${var.name}"
  description  = "Identity of the airflow-platform VM: reads its own secret slots (and pulls its own registry)."
}

# --- secret slots (no versions: values never pass through Terraform or its state) -------------

resource "google_secret_manager_secret" "slot" {
  for_each = local.secret_slots

  project   = var.project_id
  secret_id = each.value
  labels    = local.labels

  replication {
    auto {}
  }
}

# secretAccessor on each slot, for the VM's service account only (no project-wide grant).
resource "google_secret_manager_secret_iam_member" "accessor" {
  for_each = local.secret_slots

  project   = var.project_id
  secret_id = google_secret_manager_secret.slot[each.key].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.this.email}"
}

# --- network: IAP-only ingress, NAT egress ---------------------------------------------------

resource "google_compute_firewall" "iap" {
  project     = var.project_id
  name        = "${var.name}-allow-iap"
  network     = var.network
  description = "airflow-platform ${var.name}: SSH and the Airflow UI from IAP TCP forwarding only"
  direction   = "INGRESS"
  priority    = 1000

  source_ranges = local.iap_source_ranges
  target_tags   = [var.name]

  allow {
    protocol = "tcp"
    ports    = ["22", "8080"]
  }
}

# Cloud NAT: about $0.0014/h per VM (~$0.03/day) plus $0.045/GB processed (a first boot pulls a few GB of
# images, so ~$0.10-0.20 per boot). Hence create_nat: switch it off when the network already has a NAT.
resource "google_compute_router" "this" {
  count = var.create_nat ? 1 : 0

  project = var.project_id
  name    = "${var.name}-router"
  region  = var.region
  network = var.network
}

resource "google_compute_router_nat" "this" {
  count = var.create_nat ? 1 : 0

  project                            = var.project_id
  name                               = "${var.name}-nat"
  router                             = google_compute_router.this[0].name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}

# --- optional registry -----------------------------------------------------------------------

resource "google_artifact_registry_repository" "this" {
  count = var.enable_registry ? 1 : 0

  project       = var.project_id
  location      = var.region
  repository_id = var.name
  description   = "airflow-platform ${var.name}: workload images"
  format        = "DOCKER"
  labels        = local.labels

  docker_config {
    immutable_tags = true
  }
}

resource "google_artifact_registry_repository_iam_member" "reader" {
  count = var.enable_registry ? 1 : 0

  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.this[0].name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.this.email}"
}

# --- the VM ----------------------------------------------------------------------------------

resource "google_compute_instance" "this" {
  project      = var.project_id
  name         = var.name
  zone         = var.zone
  machine_type = var.machine_type
  tags         = [var.name]
  labels       = local.labels

  boot_disk {
    auto_delete = true

    initialize_params {
      image  = "ubuntu-os-cloud/ubuntu-2404-lts-amd64" # Ubuntu 24.04 LTS image family
      size   = 30
      type   = "pd-balanced"
      labels = local.labels
    }
  }

  # No public address block: the VM is reachable through IAP only and reaches out through Cloud NAT.
  network_interface {
    network = var.network
  }

  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  service_account {
    email  = google_service_account.this.email
    scopes = ["cloud-platform"] # access is limited by IAM bindings, not scopes
  }

  metadata = {
    user-data              = local.user_data
    enable-oslogin         = "TRUE"
    block-project-ssh-keys = "TRUE"
  }

  # TTL: Compute Engine deletes the VM max_run_duration after it starts. cloud-init also runs
  # shutdown -h +ttl (shared template), which would only stop it if it ever fired first.
  dynamic "scheduling" {
    for_each = local.ttl_scheduling

    content {
      provisioning_model          = "STANDARD"
      instance_termination_action = "DELETE"
      automatic_restart           = true
      on_host_maintenance         = "MIGRATE"

      max_run_duration {
        seconds = scheduling.value
      }
    }
  }

  allow_stopping_for_update = true

  lifecycle {
    # A newer image in the family must not replace a running VM; recreate it on purpose.
    ignore_changes = [boot_disk[0].initialize_params[0].image]
  }

  depends_on = [google_secret_manager_secret_iam_member.accessor, google_compute_router_nat.this]
}
