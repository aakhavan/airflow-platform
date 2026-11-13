"""S7 acceptance: AWS module validates and its mock-provider tests pass. No cloud calls."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ROOT, check, finish, guarded, no_secrets, pytest_check, read  # noqa: E402
from _tf import module_checks  # noqa: E402

MOD = "terraform/modules/airflow-vm-aws"


def static():
    main = read(f"{MOD}/main.tf")
    check("IMDSv2 required", 'http_tokens' in main and '"required"' in main)
    check("no 0.0.0.0/0 ingress", "ingress" not in main or "0.0.0.0/0" not in main.split("egress")[0])
    check("TTL terminate wiring", "instance_initiated_shutdown_behavior" in main)
    check("registry behind enable_registry", "enable_registry" in main and "aws_ecr_repository" in main)
    check("no secret versions created", "aws_secretsmanager_secret_version" not in main)
    check("no tfvars committed", not list((ROOT / "terraform").rglob("*.tfvars")))
    check("no backend block in envs/aws", "backend" not in read("terraform/envs/aws/main.tf"))
    check("shared cloud-init template", (ROOT / "terraform/templates/cloud-init.yaml.tftpl").is_file())
    no_secrets()


guarded(static)
guarded(module_checks, MOD, "terraform/envs/aws")
guarded(pytest_check, "tests", ["test_no_tfvars_committed", "test_no_backend_block_in_envs", "test_cloud_init_has_no_secret_values",
                                "test_template_shared_by_both_clouds_has_cloud_switch"])
finish("S7")
