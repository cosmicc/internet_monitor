FROM python:3.12-slim

# Install system dependencies: fping for ICMP, ca-certificates for HTTPS
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        fping \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
RUN pip install --no-cache-dir \
    flask \
    pytz \
    requests

# Application files
COPY internet_monitor.py /app/internet_monitor.py
COPY log_viewer.py       /app/log_viewer.py
COPY healthcheck.py      /app/healthcheck.py
COPY templates/          /app/templates/
COPY entrypoint.sh       /entrypoint.sh

RUN chmod +x /entrypoint.sh

# Ensure log directory exists
RUN mkdir -p /var/log

ENV INTERNET_MONITOR_CONFIG=/config/config.ini
ENV PYTHONUNBUFFERED=1
ENV FLASK_ENV=production

# Expose default web port (actual port is configurable in config.ini, but 5005 is the default)
EXPOSE 5005

# Healthcheck uses healthcheck.py which reads the real port from config.ini
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -u /app/healthcheck.py || exit 1

ENTRYPOINT ["/entrypoint.sh"]
