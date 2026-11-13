# airflow-platform image: the official Airflow image plus providers, nothing else (ADR 0001).
# The version lives in this one ARG; stack/versions.yaml records it.
ARG AIRFLOW_VERSION=3.3.2
FROM apache/airflow:${AIRFLOW_VERSION}-python3.12

ARG AIRFLOW_VERSION

COPY requirements.txt /requirements.txt

# Pin apache-airflow itself so pip never up/downgrades core, and let the official
# constraints file pin every provider.
RUN pip install --no-cache-dir \
      "apache-airflow==${AIRFLOW_VERSION}" \
      -r /requirements.txt \
      --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-3.12.txt"
