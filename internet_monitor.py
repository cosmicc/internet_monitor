import socket
import os
import subprocess
import time
import datetime
import configparser
import pushover

PING_HOST = "1.1.1.1"
DNS_HOST = "www.google.com"

def logf(status, message):
    if status:
        schar = "(+)"
    else:
        schar = "(-)"
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_message = f"{timestamp} {schar} {message}\n"
    with open('/var/log/connection.log', 'a') as log_file:
        log_file.write(log_message)

def check_internet():
    try:
        subprocess.check_output(
            ["fping", PING_HOST]
        )
        return True
    except subprocess.CalledProcessError:
        return False

def check_dns():
    try:
        # Try to resolve a known domain
        socket.gethostbyname(DNS_HOST)
        return True
    except socket.error:
        return False

def send_pushover_notification(message, title):
    # Send pushover notification
    try:
        client = pushover.PushoverClient("/etc/pushover2.creds")
        client.send_message(message, title=title)
        #print(f"Pushover notification sent: {message}")
    except Exception as e:
        print(f"Failed to send pushover notification: {e}")
        logf(False, f"Failed to send pushover notification: {e}")

internet_up = True
dns_up = True
ping_fail_count = 0
high_latency_count = 0
ping_fail_time = None
high_latency_time = None
notified = False
print("Starting Internet Monitor Service")
while True:
    start_time = time.time() 
    if check_internet():
        if not internet_up:
            downtime = datetime.datetime.now() - ping_fail_time
            if not notified:
                print(f"Internet check ping failed")
                logf(False, f"Internet check ping failed")
                notified = True
            if ping_fail_count >= 3:
                downtime = datetime.datetime.now() - ping_fail_time
                send_pushover_notification(f"Internet is back from outage: {downtime}.", "Internet Outage")
                print(f"Internet is back from outage: {downtime}.")
                logf(True, f"Internet is back from outage: {downtime}")
                notified = False
            internet_up = True
            ping_fail_count = 0
            ping_fail_time = None
            high_latency_time = None
        else:
            try:
                ping_output = subprocess.check_output(
                    ["fping", "-c", "3", PING_HOST],
                    stderr=subprocess.DEVNULL,
                    text=False,
                )
                ping_time = int((ping_output.decode()).split(" ")[7])
                if ping_time > 1000:
                    print(f"Latency check ping high: {ping_time}ms")
                    logf(False, f"Latency check ping high: {ping_time}ms")
                    if high_latency_count == 0:
                        high_latency_time = datetime.datetime.now()
                    high_latency_count += 1
                    if high_latency_count == 3 and not notified:
                        avg_latency = ping_time * high_latency_count
                        send_pushover_notification(f"High internet latency! Average latency: {avg_latency}", "High Latency")
                        print(f"High internet latency! Average latency: {avg_latency}")
                        logf(False, f"High Internet latency! Average Latency: {avg_latency}")
                        notified = True
                else:
                    if high_latency_count >= 3:
                        downtime = datetime.datetime.now() - high_latency_time
                        send_pushover_notification(f"Internet has recovered from high latency: {downtime}.", "Latency Recovered")
                        print(f"Internet has recovered from high latency: {downtime}.")
                        logf(True, f"Connection has recovered from high latency: {downtime}")
                        notified = False
                    high_latency_count = 0
                    high_latency_time = None
                    dns_state = check_dns()
                if (not dns_state and dns_up and not notified):
                    print("DNS Resolution failure")
                    logf(False, "DNS resolution failure")
                    send_pushover_notification("DNS resolution failure", "DNS Failure")
                    notified = True
                if (dns_state and not dns_up):
                    print("DNS has recovered from failure")
                    logf(True, "DNS has recovered from failure")
                    send_pushover_notification("DNS has recovered from failure", "DNS Recovered")
                    notified = False
                dns_up = dns_state
            except (subprocess.CalledProcessError, ValueError):
                pass

    else:
        if internet_up:
           ping_fail_time = datetime.datetime.now()
        ping_fail_count += 1
        internet_up = False

    current_time = time.time()
    elapsed_time = current_time - start_time
    if elapsed_time < 10:
        time.sleep(.1)
