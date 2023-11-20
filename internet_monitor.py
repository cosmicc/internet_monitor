import socket
import os
import re
import subprocess
import time
import pytz
from datetime import datetime, timedelta
import configparser
import pushover

DEBUG = False  # More verbose output
PING_HOST = "8.8.8.8"
DNS_HOST = "www.google.com"
PINGS = 5 # number of pings to get average
INTERVAL = 60  # seconds
TRIGGER = 3  # alert after number of misses

#===========NO CHANGES BELOW THIS LONE------------------
internet_up = False
loss_percentage_count = 0

utc_datetime = datetime.utcnow().replace(tzinfo=pytz.utc)
est_timezone = pytz.timezone('US/Eastern')

def logf(status, message):
    if status:
        schar = "(+)"
    else:
        schar = "(-)"
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    log_message = f"{timestamp} {schar} {message}\n"
    with open('/var/log/connection.log', 'a') as log_file:
        log_file.write(log_message)

def check_dns():
    try:
        socket.gethostbyname(DNS_HOST)
        return True
    except socket.error:
        return False

def send_pushover_notification(message, title):
    try:
        client = pushover.PushoverClient("/etc/pushover2.creds")
        client.send_message(message, title=title)
        if DEBUG:
            logf(True, f"Pushover notification sent: {message}")
    except Exception as e:
        logf(False, f"Failed to send pushover notification: {e}")

def tz(dt):
    dtd = dt.replace(tzinfo=pytz.utc)
    est_datetime = dtd.astimezone(est_timezone)
    if DEBUG:
        print(f"UTC Timestamp: {dt.strftime('%c')}")     
        print(f"EST Timestamp: {est_datetime.strftime('%c')}")
    return est_datetime

def format_time(seconds):
    try:
        time_delta = timedelta(seconds=seconds)
        hours, remainder = divmod(time_delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        time_parts = []
        if hours > 0:
            time_parts.append(f"{hours} {'hour' if hours == 1 else 'hours'}")
        if minutes > 0:
            time_parts.append(f"{minutes} {'minute' if minutes == 1 else 'minutes'}")
        if seconds > 0 or not time_parts:
            time_parts.append(f"{seconds} {'second' if seconds == 1 else 'seconds'}")
        formatted_time = ", ".join(time_parts)
        return formatted_time
    except Exception as e:
        logf(False, "Format Time Error: {str(e)}")

dns_up = True
dns_fail_count = 0
ping_fail_count = 0
high_latency_count = 0
ping_fail_time = datetime.now()
high_latency_time = datetime.now()
notified = False
if DEBUG:
    print("Starting Internet Monitor Service in DEBUG MODE")
    print(f"Number of pings: {PINGS} pings for average")
    print(f"Check Interval: {INTERVAL} Seconds")
    print(f"Alert Trigger: {TRIGGER} Iterations")
    logf(True, f"Starting Internet Monitor Service in DEBUG MODE, Interval: {INTERVAL} Seconds, {TRIGGER} Interations. {PINGS} Pings for average")
else:
    print("Starting Internet Monitor Service")
    logf(True, "Starting Internet Monitor Service")

while True:
    start_time = time.time() 
    try:
        ping_output = subprocess.run(['fping', '-c', f"{PINGS}", PING_HOST], capture_output=True, text=True, check=True)
        pattern = r'(\d+\.\d+)/(\d+\.\d+)/(\d+\.\d+)'
        pingout = ping_output.stderr
        #print(ping_output.stderr)
        match = re.search(pattern, pingout)
        if match:
            ping_time = float(match.group(2))
            if DEBUG:
                logf(True, f"Avg Ping Time: {ping_time}")       
        else:
            logf(False, "Unable to parse fping output to get ping time")
            ping_time = 99999
        plpattern = r'(\d+)%, '
        plmatch = re.search(plpattern, pingout)
        if plmatch:
            loss_percentage = int(plmatch.group(1))
            if loss_percentage == 0:
                if loss_percentage_count == TRIGGER:
                    downtime = int((datetime.now() - loss_percentage_time).total_seconds())
                    datetime_object = datetime.utcfromtimestamp(int(loss_percentage_time.timestamp()))
                    formatted_datetime = datetime_object.strftime('%c')
                    send_pushover_notification(f"Internet has recovered from packet loss of {loss_percentage}% from {formatted_datetime} which was {format_time(downtime)} ago", "Packet Loss")
                    logf(True, f"Alert: Internet has recovered from packet loss of {loss_percentage}% from {formatted_datetime} which was for {format_time(downtime)} in length")
                    notified = False

                loss_percentage_count = 0
                loss_percentage_time = datetime.now()
            if DEBUG:
                logf(True, f"Packet Loss: {loss_percentage}%")
            if loss_percentage > 0:
                logf(True, f"Packet Loss: {loss_percentage}%")
                loss_percentage_count += 1
                loss_percentage_time = datetime.utcnow()
                if loss_percentage_count >= TRIGGER:
                    send_pushover_notification(f"Internet packet loss of {loss_percentage}% detected", "Packet Loss")
                    logf(True, f"Alert: Internet packet loss of {loss_percentage}% detected")
                    notified = True

        else:
           logf(False, "Unable to parse fping output to get packet loss")
           loss_percentage = 99999
        if ping_fail_count >= TRIGGER:
            downtime = int((datetime.utcnow() - ping_fail_time).total_seconds())
            datetime_object = datetime.utcfromtimestamp(int(ping_fail_time.timestamp()))
            formatted_datetime = tz(datetime_object).strftime('%c')
            send_pushover_notification(f"Internet is back from outage that started {formatted_datetime} which was for {format_time(downtime)} in length", "Internet Outage")
            logf(True, f"Alert: Internet is back from outage that started {formatted_datetime} {format_time(downtime)} ago")
            notified = False
        ping_fail_time = datetime.utcnow()
        ping_fail_count = 0
        internet_up = True

    except subprocess.CalledProcessError as e:
        ping_fail_count += 1
        internet_up = False
        if DEBUG:
            logf(False, f"Missed ping to {PING_HOST} count ({ping_fail_count}/{TRIGGER})")
        if ping_fail_count == 1:
            ping_fail_time = datetime.utcnow()
        if ping_fail_count >= TRIGGER and not notified:
            logf(False, f"Alert: Internet is DOWN! Ping to {PING_HOST} has failed ({ping_fail_count}/{TRIGGER})")
            notified = True

    if ping_time > 1000:
        high_latency_count += 1
        if DEBUG:
            logf(False, f"High Internet latency of {ping_time}ms detected count ({high_latency_count}/{TRIGGER})") 
        if high_latency_count == 0:
            high_latency_time = datetime.utcnow()
        if high_latency_count >= TRIGGER and not notified:
            send_pushover_notification(f"High Internet latency has been detected. Average latency: {ping_time}", "High Latency")
            logf(False, f"Alert: High Internet latency has been detected. Average Latency: {ping_time}")
            notified = True
    else:
        if high_latency_count >= TRIGGER:
            downtime = int((datetime.utcnow() - high_latency_time).total_seconds())
            datetime_object = datetime.utcfromtimestamp(int(high_latency_time.timestamp()))
            formatted_datetime = tz(datetime_object.strftime('%c'))
            send_pushover_notification(f"Internet has recovered from high latency that started {formatted_datetime} which was for {format_time(downtime)} in length", "Latency Recovered")
            logf(True, f"Alert: Internet has recovered from high latency that started {formatted_datetime} {format_time(downtime)} ago")
            notified = False
        high_latency_count = 0
        high_latency_time = datetime.now()
        if internet_up:
            dns_state = check_dns()
            if (not dns_state and dns_up):
                dns_fail_count += 1
                if dns_fail_count >= 3:
                    logf(False, "Alert: DNS resolution failure")
                    send_pushover_notification("DNS resolution failure", "DNS Failure")
            if (dns_state and not dns_up):
                if dns_fail_count >= 3:
                    logf(True, "Alert: DNS has recovered from failure")
                    send_pushover_notification("DNS has recovered from failure", "DNS Recovered")
                dns_fail_count = 0
            dns_up = dns_state

    while time.time() - start_time < INTERVAL:
        time.sleep(1)
