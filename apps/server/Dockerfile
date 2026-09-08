FROM python:3.12-slim

WORKDIR /app
COPY apps/server/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY apps/server/*.py ./

ENV DB_PATH=/data/project.db
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
