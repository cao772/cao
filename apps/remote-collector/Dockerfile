FROM python:3.12-slim

WORKDIR /app
COPY apps/remote-collector/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY apps/remote-collector/gitlab_collector.py ./gitlab_collector.py

ENV GITLAB_PROJECTS_CONFIG=/config/gitlab-projects.yaml \
    REMOTE_COLLECTOR_STATE=/state/gitlab-state.json \
    POLL_INTERVAL_SECONDS=300

CMD ["python", "gitlab_collector.py"]
