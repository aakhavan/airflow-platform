"""S8 acceptance: GCP module validates and its mock-provider tests pass; AWS still passes. No cloud calls."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT, check, finish, guarded, no_secrets, pytest_check, read  # noqa: E402
from _tf import module_checks  # noqa: E402

MOD = "terraform/modules/airflow-vm-gcp"


def static():
    main = read(f"{MOD}/main.tf")
    check("IAP range only", "35.235.240.0/20" in main and "0.0.0.0/0" not in main)
    check("no external IP", "access_config" not in main)
    check("TTL scheduling", "max_run_duration" in main and "DELETE" in main)
    check("Shielded VM", "shielded_instance_config" in main)
    check("registry behind enable_registry", "enable_registry" in main and "google_artifact_registry_repository" in main)
    check("no secret versions created", "google_secret_manager_secret_version" not in main)
    check("one shared cloud-init template", len(list((ROOT / "terraform").rglob("*.tftpl"))) == 1)
    no_secrets()


guarded(static)
guarded(module_checks, MOD, "terraform/envs/gcp")
guarded(module_checks, "terraform/modules/airflow-vm-aws", "terraform/envs/aws")
guarded(pytest_check, "tests", ["test_gcp_module_has_no_external_ip_block"])
finish("S8")
