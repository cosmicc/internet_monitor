#!/bin/sh
set -eu

echo "[entrypoint] Using config: ${INTERNET_MONITOR_CONFIG:-/config/config.ini}"

# Start the internet monitor in the background
python -u /app/internet_monitor.py &

# Start the Flask log viewer (0.0.0.0:5005 as coded in log_viewer.py)
python -u /app/log_viewer.py
