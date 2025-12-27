FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt /app/requirements.txt
RUN apt-get update \
    && apt-get install -y cron \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r /app/requirements.txt

COPY . /app
COPY cron/arxiv_sanity /etc/cron.d/arxiv_sanity
RUN chmod 0644 /etc/cron.d/arxiv_sanity

EXPOSE 4000
