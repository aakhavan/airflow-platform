"""The platform's example workload: run airflow-platform/hello:local through the socket proxy.

Imports only airflow, providers and the stdlib (ADR 0001): the work happens in the container.
"""
from __future__ import annotations

from airflow.providers.docker.operators.docker import DockerOperator
from airflow.sdk import DAG, Variable

DOCKER_URL = Variable.get("docker_url", default="tcp://docker-proxy:2375")

with DAG(
    dag_id="hello_workload",
    schedule=None,
    catchup=False,
    tags=["platform"],
    doc_md=__doc__,
):
    DockerOperator(
        task_id="hello",
        image="airflow-platform/hello:local",
        docker_url=DOCKER_URL,
        mount_tmp_dir=False,
        auto_remove="success",
    )
