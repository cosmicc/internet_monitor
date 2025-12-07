#!/usr/bin/env python3
"""
Internet health monitor with:

- ICMP reachability check using fping
- Packet loss & latency monitoring
- DNS resolution checks
- Pushover notifications, queued while the internet is down
- Logging to a configurable log file (created if missing)
- Config-driven thresholds and targets via config.ini

Intended to be run as a long-lived process (systemd, docker, tmux, etc.).
"""

import os
import sys
import re
import socket
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, List, Tuple

import pytz
import configparser
import requests


# ======================================
# DEFAULTS & GLOBAL CONFIG OVERRIDES
# ======================================

# Path to config file (can be overridden via env)
CONFIG_PATH = os.environ.get("INTERNET_MONITOR_CONFIG", "/config/config.ini")

# Defaults (overridden by config.ini if present)
DEBUG: bool = False

PING_HOST: str = "8.8.8.8"
DNS_HOST: str = "www.google.com"

PINGS: int = 5
INTERVAL: int = 60
TRIGGER: int = 3
HIGH_LATENCY_MS: float = 1000.0
DNS_FAILURE_TRIGGER: int = 3

LOG_PATH: str = "/var/log/connection.log"
TIMEZONE: str = "America/Detroit"

# Pushover defaults (token/user MUST be overridden in config for notifications to work)
PUSHOVER_TOKEN: str = ""
PUSHOVER_USER: str = ""
PUSHOVER_DEVICE: str = ""          # optional
PUSHOVER_PRIORITY: int = 0         # default priority 0

# Will be set from TIMEZONE at runtime
LOCAL_TZ = pytz.timezone(TIMEZONE)


# ======================================
# CONFIG LOADING
# ======================================

def load_config(path: str) -> None:
    """
    Load configuration from an INI file and override globals.

    Example:

        [monitor]
        debug = false
        ping_host = 8.8.8.8
        dns_host = www.google.com
        pings = 5
        interval = 60
        trigger = 3
        high_latency_ms = 1000
        dns_failure_trigger = 3
        log_path = /var/log/connection.log
        timezone = America/Detroit

        [pushover]
        token = YOUR_APP_TOKEN
        user = YOUR_USER_KEY
        device =                      ; optional (empty = all devices)
        priority = 0                  ; optional, default 0
    """
    global DEBUG, PING_HOST, DNS_HOST, PINGS, INTERVAL, TRIGGER
    global HIGH_LATENCY_MS, DNS_FAILURE_TRIGGER, LOG_PATH, TIMEZONE
    global PUSHOVER_TOKEN, PUSHOVER_USER, PUSHOVER_DEVICE, PUSHOVER_PRIORITY
    global LOCAL_TZ

    parser = configparser.ConfigParser()
    read_files = parser.read(path)

    if not read_files:
        print(f"WARNING: config file {path} not found, using built-in defaults.",
              file=sys.stderr)
        LOCAL_TZ = pytz.timezone(TIMEZONE)
        return

    # Helper accessors
    def get_bool(section: str, option: str, default: bool) -> bool:
        if parser.has_option(section, option):
            return parser.getboolean(section, option)
        return default

    def get_int(section: str, option: str, default: int) -> int:
        if parser.has_option(section, option):
            return parser.getint(section, option)
        return default

    def get_float(section: str, option: str, default: float) -> float:
        if parser.has_option(section, option):
            return parser.getfloat(section, option)
        return default

    def get_str(section: str, option: str, default: str) -> str:
        if parser.has_option(section, option):
            return parser.get(section, option)
        return default

    # [monitor]
    section = "monitor"
    DEBUG = get_bool(section, "debug", DEBUG)
    PING_HOST = get_str(section, "ping_host", PING_HOST)
    DNS_HOST = get_str(section, "dns_host", DNS_HOST)
    PINGS = get_int(section, "pings", PINGS)
    INTERVAL = get_int(section, "interval", INTERVAL)
    TRIGGER = get_int(section, "trigger", TRIGGER)
    HIGH_LATENCY_MS = get_float(section, "high_latency_ms", HIGH_LATENCY_MS)
    DNS_FAILURE_TRIGGER = get_int(section, "dns_failure_trigger", DNS_FAILURE_TRIGGER)
    LOG_PATH = get_str(section, "log_path", LOG_PATH)
    TIMEZONE = get_str(section, "timezone", TIMEZONE)

    # [pushover]
    section = "pushover"
    PUSHOVER_TOKEN = get_str(section, "token", PUSHOVER_TOKEN)
    PUSHOVER_USER = get_str(section, "user", PUSHOVER_USER)
    PUSHOVER_DEVICE = get_str(section, "device", PUSHOVER_DEVICE)
    PUSHOVER_PRIORITY = get_int(section, "priority", PUSHOVER_PRIORITY)

    # Update timezone object
    try:
        LOCAL_TZ = pytz.timezone(TIMEZONE)
    except Exception as e:
        print(f"WARNING: invalid timezone '{TIMEZONE}' in config: {e}. "
              f"Falling back to UTC.", file=sys.stderr)
        LOCAL_TZ = pytz.utc


# ======================================
# TIME & LOGGING UTILITIES
# ======================================

def utcnow() -> datetime:
    """Return timezone-aware UTC now."""
    return datetime.now(tz=pytz.utc)


def to_local(dt: datetime) -> datetime:
    """
    Convert a timezone-aware UTC datetime to local timezone.
    If dt is naive, assume it is UTC.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=pytz.utc)
    return dt.astimezone(LOCAL_TZ)


def format_local(dt: datetime) -> str:
    """Format a datetime in local time for logs/notifications."""
    return to_local(dt).strftime("%Y-%m-%d %H:%M:%S %Z")


def format_duration(seconds: int) -> str:
    """
    Format a duration in seconds as 'X hours, Y minutes, Z seconds'.
    """
    try:
        delta = timedelta(seconds=int(seconds))
        total_seconds = int(delta.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, secs = divmod(remainder, 60)

        parts = []
        if hours:
            parts.append(f"{hours} hour" + ("s" if hours != 1 else ""))
        if minutes:
            parts.append(f"{minutes} minute" + ("s" if minutes != 1 else ""))
        if secs or not parts:
            parts.append(f"{secs} second" + ("s" if secs != 1 else ""))

        return ", ".join(parts)
    except Exception as e:
        logf(False, f"Format duration error: {e}")
        return f"{seconds} seconds"


def logf(ok: bool, message: str) -> None:
    """
    Append a log line to LOG_PATH.

    - Creates the parent directory if it does not exist.
    - Creates the log file if it does not exist (open with 'a' will do that).
    - Only falls back to stderr if directory or file creation fails.
    """
    status_char = "(+)" if ok else "(-)"
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} {status_char} {message}\n"

    log_dir = os.path.dirname(LOG_PATH) or "/"

    # Ensure directory exists
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception as e:
        try:
            sys.stderr.write(
                f"{ts} (-) Failed to create log directory '{log_dir}': {e}\n"
            )
            sys.stderr.write(line)
        except Exception:
            pass
        return

    # Now try to write to the log file
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        try:
            sys.stderr.write(
                f"{ts} (-) Failed to write log file '{LOG_PATH}': {e}\n"
            )
            sys.stderr.write(line)
        except Exception:
            pass


def check_dns(hostname: str) -> bool:
    """
    Simple DNS resolution check using gethostbyname.
    Returns True if the hostname resolves, False otherwise.
    """
    try:
        socket.gethostbyname(hostname)
        return True
    except socket.error:
        return False


# ======================================
# PING / FPING HANDLING
# ======================================

@dataclass
class PingResult:
    """Result of a single fping invocation."""
    success: bool
    avg_latency_ms: Optional[float]
    loss_percent: Optional[int]
    raw_output: str
    error: Optional[str] = None


def parse_fping_output(stderr_output: str) -> Tuple[Optional[float], Optional[int]]:
    """
    Parse fping stderr to extract:
    - average latency in ms
    - packet loss percentage

    Example fping line:
      8.8.8.8 : xmt/rcv/%loss = 5/5/0%, min/avg/max = 12.3/14.2/15.9

    Returns (avg_latency_ms, loss_percent).
    """
    avg_latency = None
    loss_percent = None

    # Packet loss pattern: xmt/rcv/%loss = 5/5/0%
    loss_match = re.search(r"=\s*\d+/\d+/(\d+)%", stderr_output)
    if loss_match:
        try:
            loss_percent = int(loss_match.group(1))
        except ValueError:
            loss_percent = None

    # RTT pattern: min/avg/max = a/b/c
    rtt_match = re.search(r"min/avg/max.*=\s*([\d\.]+)/([\d\.]+)/([\d\.]+)", stderr_output)
    if rtt_match:
        try:
            avg_latency = float(rtt_match.group(2))
        except ValueError:
            avg_latency = None

    return avg_latency, loss_percent


def run_ping() -> PingResult:
    """
    Run fping against PING_HOST with PINGS probes.
    Returns a PingResult with success flag, avg latency, packet loss, and raw output.

    success=True means:
        - fping exited with code 0 (host reachable)
        - Not necessarily "healthy" (high latency/packet loss still possible)
    """
    cmd = ["fping", "-c", str(PINGS), PING_HOST]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        avg_latency, loss = parse_fping_output(proc.stderr)
        if DEBUG:
            logf(True, f"fping success: avg_latency={avg_latency}ms, loss={loss}%")
        return PingResult(
            success=True,
            avg_latency_ms=avg_latency,
            loss_percent=loss,
            raw_output=proc.stderr,
            error=None,
        )
    except FileNotFoundError as e:
        msg = f"fping not found: {e}"
        logf(False, msg)
        return PingResult(
            success=False,
            avg_latency_ms=None,
            loss_percent=None,
            raw_output="",
            error=msg,
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr or ""
        avg_latency, loss = parse_fping_output(stderr)
        msg = f"fping failed with code {e.returncode}"
        if DEBUG:
            logf(False, f"{msg}. Output: {stderr.strip()}")
        return PingResult(
            success=False,
            avg_latency_ms=avg_latency,
            loss_percent=loss,
            raw_output=stderr,
            error=msg,
        )
    except Exception as e:
        msg = f"Unexpected error running fping: {e}"
        logf(False, msg)
        return PingResult(
            success=False,
            avg_latency_ms=None,
            loss_percent=None,
            raw_output="",
            error=msg,
        )


# ======================================
# PUSHOVER NOTIFICATION QUEUE (DIRECT HTTP API)
# ======================================

@dataclass
class QueuedNotification:
    """Represents a notification queued while internet is unavailable."""
    title: str
    message: str
    queued_at: datetime


class PushoverNotifier:
    """
    Pushover notification helper with:

    - Direct HTTP API calls using requests
    - Credentials taken from config.ini (token + user[, device, priority])
    - Automatic queueing if sends fail
    - Retry of queued notifications when connectivity is restored
    """

    API_URL = "https://api.pushover.net/1/messages.json"

    def __init__(
        self,
        token: str,
        user: str,
        device: str = "",
        priority: int = 0,
        debug: bool = False,
    ) -> None:
        self.token = token.strip()
        self.user = user.strip()
        self.device = device.strip()
        self.priority = priority
        self.debug = debug
        self.queue: List[QueuedNotification] = []
        self.enabled: bool = bool(self.token and self.user)
        self._warned_disabled = False

        if not self.enabled:
            logf(False, "Pushover is not fully configured (missing token or user); "
                        "notifications will be logged only.")

    def _enqueue(self, title: str, message: str) -> None:
        """Add a notification to the local queue for later delivery."""
        notif = QueuedNotification(title=title, message=message, queued_at=utcnow())
        self.queue.append(notif)
        logf(
            False,
            f"Queued Pushover notification '{title}' for later delivery "
            f"(queue size={len(self.queue)})"
        )

    def _send_http(self, title: str, message: str) -> bool:
        """
        Perform the HTTP POST to Pushover.

        Returns True on definite success (HTTP 200 + status=1),
        False on any failure (network error, bad response, non-1 status).
        """
        if not self.enabled:
            # Only complain once to avoid log spam
            if not self._warned_disabled:
                logf(False, "Pushover disabled; dropping notification.")
                self._warned_disabled = True
            return False

        payload = {
            "token": self.token,
            "user": self.user,
            "message": message,
            "title": title,
            "priority": str(self.priority),
            "timestamp": str(int(time.time())),
        }
        if self.device:
            payload["device"] = self.device

        try:
            resp = requests.post(self.API_URL, data=payload, timeout=10)
        except requests.RequestException as e:
            logf(False, f"Pushover HTTP error for '{title}': {e}")
            return False

        if resp.status_code != 200:
            logf(False, f"Pushover HTTP {resp.status_code} for '{title}': {resp.text}")
            return False

        try:
            data = resp.json()
        except ValueError as e:
            logf(False, f"Pushover JSON parse error for '{title}': {e}; body={resp.text}")
            return False

        if data.get("status") != 1:
            logf(False, f"Pushover API error for '{title}': {data}")
            return False

        if self.debug:
            logf(True, f"Pushover notification sent: {title}")
        return True

    def notify(self, title: str, message: str) -> None:
        """
        Try to send a notification immediately.
        On failure (network down, HTTP error, etc.), queue it for later.
        """
        if not self.enabled:
            # Still log to file even if Pushover is not configured
            logf(False, f"Pushover disabled; notification '{title}' not sent.")
            return

        if not self._send_http(title, message):
            self._enqueue(title, message)

    def flush_queue(self) -> None:
        """
        Attempt to send all queued notifications.
        Called after we have evidence that internet connectivity is restored.
        """
        if not self.enabled or not self.queue:
            return

        remaining: List[QueuedNotification] = []

        for notif in self.queue:
            if self._send_http(notif.title, notif.message):
                if self.debug:
                    age = int((utcnow() - notif.queued_at).total_seconds())
                    logf(
                        True,
                        f"Flushed queued notification '{notif.title}' "
                        f"(queued for {format_duration(age)})"
                    )
                continue

            # Sending failed again; keep this and everything after it
            remaining.append(notif)
            break

        self.queue = remaining


# ======================================
# MAIN MONITOR LOOP
# ======================================

def main() -> None:
    # Load config and override globals
    load_config(CONFIG_PATH)

    notifier = PushoverNotifier(
        token=PUSHOVER_TOKEN,
        user=PUSHOVER_USER,
        device=PUSHOVER_DEVICE,
        priority=PUSHOVER_PRIORITY,
        debug=DEBUG,
    )

    # Outage tracking
    ping_fail_count = 0
    outage_start: Optional[datetime] = None

    # Packet loss tracking
    loss_iter_count = 0
    loss_start: Optional[datetime] = None

    # High latency tracking
    latency_iter_count = 0
    latency_start: Optional[datetime] = None

    # DNS tracking
    dns_fail_count = 0
    dns_failure_start: Optional[datetime] = None

    if DEBUG:
        startup_msg = (
            f"Starting Internet Monitor in DEBUG mode: "
            f"interval={INTERVAL}s, trigger={TRIGGER}, pings={PINGS}, "
            f"ping_host={PING_HOST}, dns_host={DNS_HOST}"
        )
    else:
        startup_msg = "Starting Internet Monitor"

    print(startup_msg)
    logf(True, startup_msg)

    while True:
        loop_start = time.time()
        try:
            ping_result = run_ping()
        except Exception as e:
            logf(False, f"Unexpected error in ping check: {e}")
            ping_result = PingResult(
                success=False,
                avg_latency_ms=None,
                loss_percent=None,
                raw_output="",
                error=str(e),
            )

        # If fping itself is missing, there's no point looping forever
        if ping_result.error and "fping not found" in ping_result.error:
            logf(False, "Terminating monitor: fping is not installed.")
            break

        # --------------------
        # CONNECTIVITY / OUTAGE
        # --------------------
        connectivity_up = ping_result.success

        if connectivity_up:
            if ping_fail_count >= TRIGGER and outage_start is not None:
                downtime = int((utcnow() - outage_start).total_seconds())
                title = "Internet Outage Resolved"
                message = (
                    f"Internet connectivity restored. Outage started at "
                    f"{format_local(outage_start)} and lasted {format_duration(downtime)}."
                )
                notifier.notify(title, message)
                logf(True, message)

            ping_fail_count = 0
            outage_start = None
        else:
            ping_fail_count += 1
            if DEBUG:
                logf(False, f"Missed ping to {PING_HOST} ({ping_fail_count}/{TRIGGER})")

            if ping_fail_count == 1:
                outage_start = utcnow()

            if ping_fail_count == TRIGGER and outage_start is not None:
                title = "Internet Outage Detected"
                message = (
                    f"Ping to {PING_HOST} has failed {TRIGGER} consecutive checks "
                    f"since {format_local(outage_start)}."
                )
                notifier.notify(title, message)
                logf(False, message)

        # --------------------
        # PACKET LOSS & LATENCY (only meaningful when connectivity_up)
        # --------------------
        if connectivity_up and ping_result.loss_percent is not None:
            loss = ping_result.loss_percent
            avg_latency = ping_result.avg_latency_ms

            # Packet loss
            if loss > 0:
                loss_iter_count += 1
                if loss_iter_count == 1:
                    loss_start = utcnow()

                if DEBUG:
                    logf(False, f"Packet loss detected: {loss}% "
                                f"({loss_iter_count}/{TRIGGER})")

                if loss_iter_count == TRIGGER and loss_start is not None:
                    title = "Internet Packet Loss Detected"
                    message = (
                        f"Packet loss of {loss}% detected to {PING_HOST} "
                        f"for at least {TRIGGER} consecutive checks "
                        f"since {format_local(loss_start)}."
                    )
                    notifier.notify(title, message)
                    logf(False, message)
            else:
                if loss_iter_count >= TRIGGER and loss_start is not None:
                    downtime = int((utcnow() - loss_start).total_seconds())
                    title = "Internet Packet Loss Resolved"
                    message = (
                        f"Packet loss has recovered to 0% (host: {PING_HOST}). "
                        f"Loss period started at {format_local(loss_start)} and "
                        f"lasted {format_duration(downtime)}."
                    )
                    notifier.notify(title, message)
                    logf(True, message)

                loss_iter_count = 0
                loss_start = None

            # High latency
            if avg_latency is not None and avg_latency > HIGH_LATENCY_MS:
                latency_iter_count += 1
                if latency_iter_count == 1:
                    latency_start = utcnow()

                if DEBUG:
                    logf(False, f"High latency {avg_latency:.2f}ms detected "
                                f"({latency_iter_count}/{TRIGGER})")

                if latency_iter_count == TRIGGER and latency_start is not None:
                    title = "High Internet Latency Detected"
                    message = (
                        f"High latency detected: average {avg_latency:.2f} ms to {PING_HOST} "
                        f"for at least {TRIGGER} consecutive checks "
                        f"since {format_local(latency_start)}."
                    )
                    notifier.notify(title, message)
                    logf(False, message)
            else:
                if latency_iter_count >= TRIGGER and latency_start is not None:
                    downtime = int((utcnow() - latency_start).total_seconds())
                    title = "Internet Latency Recovered"
                    message = (
                        f"Latency has recovered below {HIGH_LATENCY_MS:.0f} ms "
                        f"(host: {PING_HOST}). High-latency period started at "
                        f"{format_local(latency_start)} and lasted {format_duration(downtime)}."
                    )
                    notifier.notify(title, message)
                    logf(True, message)

                latency_iter_count = 0
                latency_start = None

        # --------------------
        # DNS HEALTH (only check if connectivity_up)
        # --------------------
        if connectivity_up:
            dns_ok = check_dns(DNS_HOST)
            if dns_ok:
                if dns_fail_count >= DNS_FAILURE_TRIGGER and dns_failure_start is not None:
                    downtime = int((utcnow() - dns_failure_start).total_seconds())
                    title = "DNS Failure Resolved"
                    message = (
                        f"DNS resolution for {DNS_HOST} has recovered. "
                        f"Failure period started at {format_local(dns_failure_start)} "
                        f"and lasted {format_duration(downtime)}."
                    )
                    notifier.notify(title, message)
                    logf(True, message)

                dns_fail_count = 0
                dns_failure_start = None
            else:
                dns_fail_count += 1
                if dns_fail_count == 1:
                    dns_failure_start = utcnow()

                if DEBUG:
                    logf(False, f"DNS resolution failed for {DNS_HOST} "
                                f"({dns_fail_count}/{DNS_FAILURE_TRIGGER})")

                if dns_fail_count == DNS_FAILURE_TRIGGER and dns_failure_start is not None:
                    title = "DNS Resolution Failure"
                    message = (
                        f"DNS resolution for {DNS_HOST} has failed for "
                        f"{DNS_FAILURE_TRIGGER} consecutive checks "
                        f"since {format_local(dns_failure_start)}."
                    )
                    notifier.notify(title, message)
                    logf(False, message)

        # --------------------
        # FLUSH QUEUED NOTIFICATIONS
        # --------------------
        if connectivity_up:
            notifier.flush_queue()

        # --------------------
        # LOOP TIMING
        # --------------------
        elapsed = time.time() - loop_start
        sleep_for = max(0, INTERVAL - elapsed)
        if DEBUG:
            logf(True, f"Loop elapsed={elapsed:.2f}s, sleeping for {sleep_for:.2f}s")
        time.sleep(sleep_for)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logf(True, "Internet Monitor stopped by user (KeyboardInterrupt)")
        sys.exit(0)
    except Exception as e:
        logf(False, f"Internet Monitor crashed with unhandled exception: {e}")
        sys.exit(1)
