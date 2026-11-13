# The smallest workload: python slim + main.py. Built as airflow-platform/hello:local by
# `python -m airflow_platform.stack up` (every workloads/<name>/Dockerfile).
FROM python:3.12.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY main.py /app/main.py

USER nobody
ENTRYPOINT ["python", "/app/main.py"]
