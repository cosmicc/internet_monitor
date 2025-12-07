FROM python:3.12-slim

# Install system dependencies: fping for ICMP, ca-certificates for HTTPS
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        fping \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Work directory for the app
WORKDIR /app

# Install Python dependencies
# - flask: web UI
# - pytz: timezone handling
# - requests: Pushover HTTP API
RUN pip install --no-cache-dir \
    flask \
    pytz \
    requests

# Copy Python applications
COPY internet_monitor.py /app/internet_monitor.py
COPY log_viewer.py       /app/log_viewer.py

# Copy Flask templates
COPY templates/ /app/templates/

# Ensure log directory exists and create the log file
RUN mkdir -p /var/log && \
    touch /var/log/connection.log

# Environment variables:
# - Shared config.ini path for both monitor + viewer
# - Unbuffered Python output for real-time logs
ENV INTERNET_MONITOR_CONFIG=/config/config.ini
ENV PYTHONUNBUFFERED=1
ENV FLASK_ENV=production

# Copy entrypoint script that starts both services
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Web UI port
EXPOSE 5005

# Start both the monitor and the log viewer
ENTRYPOINT ["/entrypoint.sh"]
