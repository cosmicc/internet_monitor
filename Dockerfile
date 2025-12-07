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

# Make sure these dirs exist *inside* the container
RUN mkdir -p /var/log && mkdir -p /config/internet_monitor

# Config path inside the container
ENV INTERNET_MONITOR_CONFIG=/config/internet_monitor/config.ini
ENV PYTHONUNBUFFERED=1
ENV FLASK_ENV=production

# Default web port (actual port still comes from [web].port in config.ini)
EXPOSE 5005

# Healthcheck uses healthcheck.py, which reads INTERNET_MONITOR_CONFIG
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -u /app/healthcheck.py || exit 1

ENTRYPOINT ["/entrypoint.sh"]
