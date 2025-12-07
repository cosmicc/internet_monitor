#!/usr/bin/env bash
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Ensure config exists (optional sanity check)
if [ ! -f "${PROJECT_DIR}/config.ini" ]; then
  echo "ERROR: ${PROJECT_DIR}/config.ini not found"
  exit 1
fi

# Ensure the log file exists as a file, not a directory
LOG_PATH="${PROJECT_DIR}/connection.log"

if [ -d "${LOG_PATH}" ]; then
  echo "ERROR: ${LOG_PATH} is a directory; remove or rename it."
  exit 1
fi

if [ ! -f "${LOG_PATH}" ]; then
  echo "[run.sh] Creating empty log file at ${LOG_PATH}"
  touch "${LOG_PATH}"
fi

# Build and start via docker compose
docker compose up -d --build
