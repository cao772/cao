FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY apps/local-sentinel/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY apps/local-sentinel/sentinel.py ./sentinel.py
COPY apps/local-sentinel/document_pipeline.py ./document_pipeline.py

ENV PROJECTS_ROOT=/projects \
    SENTINEL_STATE_ROOT=/state \
    INTERVAL_SECONDS=900

CMD ["python", "sentinel.py"]
