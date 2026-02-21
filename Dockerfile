# syntax=docker/dockerfile:1

FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY scripts ./scripts

# runtime dirs
RUN mkdir -p /app/data /app/logs

ENV WEBUI_HOST=0.0.0.0 \
    WEBUI_PORT=5682

EXPOSE 5682

CMD ["python", "scripts/webui.py"]
