#!/usr/bin/env python3
"""
Simple read-only web viewer for the internet monitor log.

Features:
- Shows the last N lines from the connection log in a styled HTML table.
- Restricts access by client IP, with allowed hosts configured in config.ini.
- Reads log path and display options from the same config.ini as the monitor.
"""

import os
import sys
from typing import List, Dict, Any, Optional

from flask import Flask, request, render_template, abort
import configparser
import re
from datetime import datetime


# ==========================
# CONFIG LOADING
# ==========================

# Reuse same env var as the monitor for simplicity
CONFIG_PATH = os.environ.get("INTERNET_MONITOR_CONFIG", "/config/config.ini")

# Defaults (overridden by config.ini)
LOG_PATH = "/var/log/connection.log"
LINES_TO_SHOW = 200
ALLOWED_HOSTS: List[str] = []   # If empty, no IP restriction
PAGE_TITLE = "Internet Connection Log Viewer"


def load_config(path: str) -> None:
    """
    Load [web] and [monitor] sections from config.ini to configure:
      - LOG_PATH        (from [web].log_path or [monitor].log_path or default)
      - LINES_TO_SHOW   (from [web].lines)
      - ALLOWED_HOSTS   (from [web].allowed_hosts, comma-separated)
      - PAGE_TITLE      (from [web].title)
    """
    global LOG_PATH, LINES_TO_SHOW, ALLOWED_HOSTS, PAGE_TITLE

    parser = configparser.ConfigParser()
    read_files = parser.read(path)

    if not read_files:
        print(f"WARNING: config file {path} not found; "
              f"using built-in defaults for web viewer.",
              file=sys.stderr)
        return

    # Prefer [web].log_path, fallback to [monitor].log_path, then default
    if parser.has_option("web", "log_path"):
        LOG_PATH = parser.get("web", "log_path")
    elif parser.has_option("monitor", "log_path"):
        LOG_PATH = parser.get("monitor", "log_path")

    if parser.has_option("web", "lines"):
        try:
            LINES_TO_SHOW = parser.getint("web", "lines")
        except ValueError:
            print("WARNING: invalid [web].lines value in config; "
                  "falling back to default.",
                  file=sys.stderr)

    if parser.has_option("web", "allowed_hosts"):
        raw_hosts = parser.get("web", "allowed_hosts")
        # Comma- or space-separated list
        hosts = re.split(r"[,\s]+", raw_hosts.strip())
        ALLOWED_HOSTS = [h for h in hosts if h]
    else:
        ALLOWED_HOSTS = []

    if parser.has_option("web", "title"):
        PAGE_TITLE = parser.get("web", "title")


# Load config at import time so globals are ready
load_config(CONFIG_PATH)


# ==========================
# FLASK APP SETUP
# ==========================

app = Flask(__name__)


@app.before_request
def limit_remote_addr():
    """
    Restrict access based on client IP address.

    - If ALLOWED_HOSTS is empty, no restriction is applied.
    - Otherwise, request.remote_addr must be in ALLOWED_HOSTS.
    """
    if not ALLOWED_HOSTS:
        # No restriction configured
        return

    client_ip = request.remote_addr
    if client_ip not in ALLOWED_HOSTS:
        # You can log this if you like
        return "You're not allowed to access this resource", 403


def read_log_tail(path: str, max_lines: int) -> List[str]:
    """
    Efficiently read the last max_lines lines from a text file.

    If the file does not exist, returns an empty list.
    """
    if not os.path.exists(path):
        return []

    # Simple approach is fine given the log size is modest.
    # For very large logs, you could implement a buffered
    # backwards seek, but this is sufficient for typical use.
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError as e:
        print(f"ERROR: unable to read log file '{path}': {e}",
              file=sys.stderr)
        return []

    if max_lines <= 0:
        return lines
    return lines[-max_lines:]


def parse_log_line(line: str) -> Optional[Dict[str, Any]]:
    """
    Parse a single log line of the form:

        YYYY-MM-DD HH:MM:SS (+) Message text...

    Returns a dict with:
        {
          "raw": str,
          "timestamp": datetime | None,
          "timestamp_str": str,
          "level": "ok" | "error" | "unknown",
          "status_char": "+" | "-" | "?",
          "message": str,
        }

    If the line doesn't match the expected format, it is still returned
    with 'unknown' level.
    """
    line = line.rstrip("\n")
    if not line.strip():
        return None

    # Expected pattern: "YYYY-MM-DD HH:MM:SS (+) ...."
    # We capture timestamp, sign (+/-), and message.
    m = re.match(
        r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+\((\+|\-)\)\s+(.*)$",
        line,
    )

    ts: Optional[datetime] = None
    ts_str = ""
    status_char = "?"
    level = "unknown"
    msg = line

    if m:
        ts_str = m.group(1)
        status_char = m.group(2)
        msg = m.group(3)

        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            ts = None

        if status_char == "+":
            level = "ok"
        elif status_char == "-":
            level = "error"
        else:
            level = "unknown"

    return {
        "raw": line,
        "timestamp": ts,
        "timestamp_str": ts_str,
        "level": level,
        "status_char": status_char,
        "message": msg,
    }


@app.route("/")
def display_log():
    """
    Display the last N lines of the connection log in a simple HTML table.
    """
    lines = read_log_tail(LOG_PATH, LINES_TO_SHOW)
    entries: List[Dict[str, Any]] = []

    for line in lines:
        parsed = parse_log_line(line)
        if parsed is not None:
            entries.append(parsed)

    # Most recent entries at bottom (natural order from tail)
    # If you prefer newest first, reverse=True in template or here.
    return render_template(
        "connection_log.html",
        entries=entries,
        page_title=PAGE_TITLE,
        log_path=LOG_PATH,
        lines_to_show=LINES_TO_SHOW,
    )


if __name__ == "__main__":
    # For Docker / production, you'll typically run this behind gunicorn or similar.
    # This built-in dev server is enough for local use / testing.
    app.run(host="0.0.0.0", port=5005, debug=False)
