# 0002: Self-hosted on one VM with the same compose stack, not MWAA, Composer or Kubernetes

**Status:** accepted, 13 Nov 2026

## Context
The platform must run locally (Docker Desktop on Windows) and be deployable to AWS and GCP. Amir's experience is that managed Airflow services are often not a good fit (cost floor, lagging versions, restricted dependencies), and that a hand-built EC2 setup drifted and broke.

## Decision
Each cloud target is **one VM** (EC2 / Compute Engine) that runs **the same `stack/compose.yaml` as the laptop**, started by cloud-init from a pinned git ref. Terraform creates the VM, its identity, network rules, empty secret slots and (behind a flag) a registry. No public ports: SSM / IAP tunnels only.

## Considered options
- **MWAA / Cloud Composer.** Least operations work, but they cost a few hundred euros a month each, add version lag and a provider-specific dependency model, and give two different deployments to learn.
- **Kubernetes with the official Helm chart.** The production standard at scale and the Airflow docs' recommendation, but it adds a cluster (cost and a week of work) that a single team does not need yet. Kept as a named future target.
- **VM + compose (chosen).** Local and cloud are identical, it costs cents for a smoke test, and drift is prevented by cloud-init and pinned images rather than by hand.

## Consequences
- A single VM is a single point of failure. That's acceptable for a personal or small-team platform, and documented as such.
- The metadata database lives on the VM's disk by default. A managed database is a documented switch, not built yet.
- Moving to Kubernetes later reuses the image and the workload pattern (ADR 0001) unchanged; only the deployment layer changes.
