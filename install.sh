#!/usr/bin/env bash
set -euo pipefail

# Directory where this script & docker-compose.yml live
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Host paths you requested
HOST_CONFIG_DIR="/config/internet_monitor"
HOST_CONFIG_FILE="${HOST_CONFIG_DIR}/config.ini"
HOST_LOG_FILE="/var/log/connection.log"

echo "[run.sh] Project directory: ${PROJECT_DIR}"
echo "[run.sh] Host config file: ${HOST_CONFIG_FILE}"
echo "[run.sh] Host log file:    ${HOST_LOG_FILE}"

# Ensure config directory exists
if [ ! -d "${HOST_CONFIG_DIR}" ]; then
  echo "[run.sh] Creating config directory: ${HOST_CONFIG_DIR}"
  mkdir -p "${HOST_CONFIG_DIR}"
fi

# Seed config.ini on host from project config.ini if missing
if [ ! -f "${HOST_CONFIG_FILE}" ]; then
  if [ -f "${PROJECT_DIR}/config.ini" ]; then
    echo "[run.sh] Seeding config from ${PROJECT_DIR}/config.ini -> ${HOST_CONFIG_FILE}"
    cp "${PROJECT_DIR}/config.ini" "${HOST_CONFIG_FILE}"
  else
    echo "[run.sh] ERROR: Template config.ini not found in ${PROJECT_DIR}" >&2
    exit 1
  fi
else
  echo "[run.sh] Config already exists at ${HOST_CONFIG_FILE}, not overwriting."
fi

# Ensure host log file exists as a file (not a directory)
if [ -d "${HOST_LOG_FILE}" ]; then
  echo "[run.sh] ERROR: ${HOST_LOG_FILE} is a directory; expected a file." >&2
  exit 1
fi

if [ ! -f "${HOST_LOG_FILE}" ]; then
  echo "[run.sh] Creating empty log file at ${HOST_LOG_FILE}"
  touch "${HOST_LOG_FILE}"
fi

# Build and run via docker compose
cd "${PROJECT_DIR}"
echo "[run.sh] Running docker compose up -d --build"
docker compose up -d --build
