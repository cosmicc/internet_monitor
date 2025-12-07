#!/usr/bin/env python3
"""
Healthcheck script for Docker.

Reads INTERNET_MONITOR_CONFIG (config.ini), pulls [web].port (or default 5005),
and checks that the Flask web UI is responding with HTTP 200.
"""

import os
import sys
import configparser
import requests

CONFIG_PATH = os.environ.get("INTERNET_MONITOR_CONFIG", "/config/config.ini")
DEFAULT_PORT = 5005


def get_port_from_config() -> int:
    parser = configparser.ConfigParser()
    read_files = parser.read(CONFIG_PATH)

    if not read_files:
        return DEFAULT_PORT

    if parser.has_option("web", "port"):
        try:
            return parser.getint("web", "port")
        except ValueError:
            return DEFAULT_PORT

    return DEFAULT_PORT


def main() -> None:
    port = get_port_from_config()
    url = f"http://127.0.0.1:{port}/"

    try:
        resp = requests.get(url, timeout=5)
    except Exception as e:
        print(f"Healthcheck failed for {url}: {e}", file=sys.stderr)
        sys.exit(1)

    if resp.status_code != 200:
        print(f"Healthcheck bad status {resp.status_code} from {url}", file=sys.stderr)
        sys.exit(1)

    # Healthy
    sys.exit(0)


if __name__ == "__main__":
    main()
