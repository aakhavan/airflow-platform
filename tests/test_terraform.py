"""Offline checks of the Terraform sources (S7, S8, docs/spec.md §9). No terraform binary needed."""
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
TF = ROOT / "terraform"
TEMPLATE = TF / "templates" / "cloud-init.yaml.tftpl"
AWS = TF / "modules" / "airflow-vm-aws"
GCP = TF / "modules" / "airflow-vm-gcp"
MODULES = {"aws": AWS, "gcp": GCP}
PROVIDERS = {"aws": "hashicorp/aws", "gcp": "hashicorp/google"}
TEMPLATE_VARS = {"repo_url", "repo_ref", "cloud", "secret_names", "secret_prefix", "ttl_minutes", "region"}
DEFAULT_SECRETS = ("AIRFLOW__API_AUTH__JWT_SECRET", "FERNET_KEY", "_AIRFLOW_WWW_USER_PASSWORD")


def _strip_comments(text: str) -> str:
    return "\n".join(re.sub(r"(#|//).*$", "", line) for line in text.splitlines())


def _template_identifiers(text: str) -> set[str]:
    """Identifiers used inside ${...} interpolations and %{...} directives ($${...} is a literal)."""
    exprs = re.findall(r"(?<!\$)\$\{([^}]*)\}", text) + re.findall(r"%\{~?\s*([^}]*?)~?\}", text)
    words = set()
    for expr in exprs:
        expr = re.sub(r'"[^"]*"', "", expr)
        words |= set(re.findall(r"[A-Za-z_]\w*", expr))
    return words - {"join", "if", "endif", "for", "endfor", "in", "else"}


def test_no_tfvars_committed():
    assert not list(TF.rglob("*.tfvars"))
    assert not list(TF.rglob("*.tfvars.json"))
    for env in (TF / "envs").iterdir():
        if env.is_dir():
            assert (env / "terraform.tfvars.example").is_file(), env.name


def test_no_backend_block_in_envs():
    envs = list((TF / "envs").rglob("*.tf"))
    assert envs
    for f in envs:
        assert not re.search(r"\bbackend\s+\"", _strip_comments(f.read_text(encoding="utf-8"))), f.name
        assert f.name != "backend.tf", "backend.tf is written by remote-state.ps1, never committed"


def test_cloud_init_template_has_no_secret_values():
    text = TEMPLATE.read_text(encoding="utf-8")
    # Only the documented template variables are interpolated; none of them carries a value.
    assert _template_identifiers(text) <= TEMPLATE_VARS
    # No secret key is assigned a literal anywhere in the template.
    for key in DEFAULT_SECRETS:
        assert not re.search(rf"\b{key}=", text), key


@pytest.mark.parametrize("cloud", sorted(MODULES))
def test_module_passes_only_names_to_cloud_init(cloud):
    mod = MODULES[cloud]
    main = (mod / "main.tf").read_text(encoding="utf-8")
    call = re.search(r"templatefile\([^{]*\{(.*?)\}\)", main, re.S)
    assert call
    passed = set(re.findall(r"^\s*(\w+)\s*=", call.group(1), re.M))
    assert passed == TEMPLATE_VARS
    assert "../../templates/cloud-init.yaml.tftpl" in main
    assert re.search(rf'^\s*cloud\s*=\s*"{cloud}"', call.group(1), re.M)
    # No variable of the module holds a value, and no secret version is ever created.
    variables = re.findall(r'variable\s+"(\w+)"', (mod / "variables.tf").read_text(encoding="utf-8"))
    assert not [v for v in variables if re.search(r"value|password|token|key$", v)]
    assert "aws_secretsmanager_secret_version" not in main
    assert "google_secret_manager_secret_version" not in main


def test_template_shared_by_both_clouds_has_cloud_switch():
    text = TEMPLATE.read_text(encoding="utf-8")
    assert 'CLOUD="${cloud}"' in text
    assert re.search(r"^\s*aws\)", text, re.M) and re.search(r"^\s*gcp\)", text, re.M)
    assert "aws secretsmanager get-secret-value" in text
    assert "gcloud secrets versions access" in text
    assert "SecretsManagerBackend" in text and "CloudSecretManagerBackend" in text
    assert "up --projects projects/ci.yaml" in text
    assert "shutdown -h +${ttl_minutes}" in text and "%{ if ttl_minutes > 0" in text
    assert "download.docker.com/linux/ubuntu" in text and "docker-compose-plugin" in text
    assert len(list(TF.rglob("*.tftpl"))) == 1, "one shared template, never forked"


def test_aws_module_wiring():
    main = (AWS / "main.tf").read_text(encoding="utf-8")
    assert 'http_tokens   = "required"' in main
    assert 'ingress     = []' in main
    assert re.search(r"count\s*=\s*var\.enable_registry \? 1 : 0", main)
    assert 'var.ttl_minutes > 0 ? "terminate" : "stop"' in main
    assert "/aws/service/canonical/ubuntu/server/24.04/" in main
    assert list((AWS / "tests").glob("*.tftest.hcl"))
    test = (AWS / "tests" / "main.tftest.hcl").read_text(encoding="utf-8")
    assert 'mock_provider "aws"' in test and "ttl_minutes     = 90" in test and "enable_registry = true" in test
    assert test.count("command = plan") >= 2


def test_gcp_module_has_no_external_ip_block():
    main = _strip_comments((GCP / "main.tf").read_text(encoding="utf-8"))
    assert "access_config" not in main  # no ephemeral or static public IP
    assert re.search(r"network_interface\s*\{", main)
    assert re.search(r'resource\s+"google_compute_router_nat"', main), "egress goes through Cloud NAT"


def test_gcp_module_wiring():
    main = (GCP / "main.tf").read_text(encoding="utf-8")
    code = _strip_comments(main)
    assert "0.0.0.0/0" not in main
    assert '["35.235.240.0/20"]' in code and 'ports    = ["22", "8080"]' in code
    assert "target_tags   = [var.name]" in code and "tags         = [var.name]" in code
    assert "shielded_instance_config" in code and 'type   = "pd-balanced"' in code and "size   = 30" in code
    assert "ubuntu-os-cloud/ubuntu-2404-lts-amd64" in code
    assert re.search(r'dynamic\s+"scheduling"', code) and 'instance_termination_action = "DELETE"' in code
    assert 'provisioning_model          = "STANDARD"' in code and "max_run_duration" in code
    assert re.search(r"count\s*=\s*var\.enable_registry \? 1 : 0", code)
    assert 'role      = "roles/secretmanager.secretAccessor"' in code
    # secretAccessor is bound per secret, never on the project.
    assert "google_project_iam" not in code
    test = (GCP / "tests" / "main.tftest.hcl").read_text(encoding="utf-8")
    assert 'mock_provider "google"' in test and "ttl_minutes     = 90" in test and "enable_registry = true" in test
    assert test.count("command = plan") >= 2 and "expect_failures = [var.machine_type]" in test


@pytest.mark.parametrize("cloud", sorted(MODULES))
def test_terraform_versions_recorded(cloud):
    versions = yaml.safe_load((ROOT / "stack" / "versions.yaml").read_text(encoding="utf-8"))["terraform"]
    constraint = versions["providers"][PROVIDERS[cloud]]["constraint"]
    for f in (MODULES[cloud] / "versions.tf", TF / "envs" / cloud / "main.tf"):
        text = f.read_text(encoding="utf-8")
        assert f'required_version = "{versions["required_version"]}"' in text, f.name
        assert re.search(rf'version\s*=\s*"{re.escape(constraint)}"', text), f.name


def test_envs_have_the_same_shape():
    for cloud, mod in MODULES.items():
        env = TF / "envs" / cloud
        assert {f.name for f in env.glob("*.tf")} == {"main.tf", "variables.tf", "outputs.tf"}, cloud
        assert f'source = "../../modules/{mod.name}"' in (env / "main.tf").read_text(encoding="utf-8")
