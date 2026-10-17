# Airflow image with the cleaning dependencies baked in (reproducible, no install at container start).
FROM apache/airflow:2.10.5-python3.11

COPY requirements-clean.txt /requirements-clean.txt
# Airflow is pinned in the same command so pip can never change its version.
RUN pip install --no-cache-dir "apache-airflow==2.10.5" -r /requirements-clean.txt
