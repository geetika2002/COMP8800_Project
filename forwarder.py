# forwarder.py
# Streams Cowrie Docker logs, extracts relevant security events,
# and forwards them to the FastAPI collector for storage and analysis.

import subprocess
import requests
import time
from datetime import datetime
import re
import sys

# FastAPI collector endpoint
COLLECTOR = "http://127.0.0.1:8000/api/events"

# Cowrie honeypot container name
DOCKER_CONTAINER = "cowrie"

# Start streaming Cowrie logs in real time
proc = subprocess.Popen(
    ["docker", "logs", "-f", "--tail", "0", DOCKER_CONTAINER],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    bufsize=1
)

# -----------------------------
# Log parsing patterns
# -----------------------------

# Command execution patterns seen in Cowrie logs
cmd_re = re.compile(r"\] .*CMD:\s*(.+)$")
found_re = re.compile(r"Command found:\s*(.+)$")

# Extract source IP address
ip_re = re.compile(r"(\d+\.\d+\.\d+\.\d+)")

# Extract real Cowrie session_id from "New connection" log lines
new_conn_re = re.compile(
    r"New connection:\s+(\d+\.\d+\.\d+\.\d+):\d+.*\[\s*session:\s*([a-f0-9]+)\s*\]"
)

# Map source IP → most recently observed Cowrie session_id
# (sufficient for local testing and low concurrency)
ip_to_session = {}

def extract_ip(line: str) -> str:
    m = ip_re.search(line)
    return m.group(1) if m else "unknown"

def learn_session_mapping(line: str):
    """
    Learn the Cowrie session_id when a new SSH connection is logged,
    allowing later commands to be correlated to the correct session.
    """
    m = new_conn_re.search(line)
    if not m:
        return

    ip, sid = m.group(1), m.group(2)
    ip_to_session[ip] = sid
    print(f"LEARNED SESSION: ip={ip} session_id={sid}")

def current_session_id_for(line: str):
    """
    Resolve the session_id for this log line based on source IP.
    """
    return ip_to_session.get(extract_ip(line))

def parse_line(line: str):
    """
    Parse a single Cowrie log line.

    If the line contains a command execution or login attempt,
    return a structured event dictionary compatible with /api/events.
    Otherwise, return None.
    """
    line = line.strip()

    # Update IP → session_id mapping if this is a new connection
    learn_session_mapping(line)

    # Command execution
    m = cmd_re.search(line) or found_re.search(line)
    if m:
        return {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "session_id": current_session_id_for(line),
            "src_ip": extract_ip(line),
            "src_port": None,
            "dest_service": "ssh",
            "username": None,
            "command": m.group(1).strip(),
            "meta_data": line,
        }

    # Login attempts (treated as a synthetic command)
    if "unauthorized login" in line.lower() or "login attempt" in line.lower():
        return {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "session_id": current_session_id_for(line),
            "src_ip": extract_ip(line),
            "src_port": None,
            "dest_service": "ssh",
            "username": None,
            "command": "login_attempt",
            "meta_data": line,
        }

    return None

def post_event(ev):
    """
    Forward a parsed event to the FastAPI collector.
    """
    try:
        resp = requests.post(COLLECTOR, json=ev, timeout=20)
        rid = resp.json().get("id") if resp.status_code in (200, 201) else "n/a"
        print(
            f"POST -> {resp.status_code} {resp.reason} | "
            f"id={rid} | session_id={ev.get('session_id')}"
        )
    except Exception as e:
        print("Failed to POST:", e, file=sys.stderr)

# -----------------------------
# Main loop
# -----------------------------

print("Forwarder started, following container:", DOCKER_CONTAINER)

# Continuously read Cowrie logs, parse relevant lines,
# and forward extracted events to the collector.
while True:
    line = proc.stdout.readline()

    if not line:
        time.sleep(0.1)
        continue

    raw = line.strip()
    print("RAW:", raw)

    ev = parse_line(raw)
    if ev:
        print("POSTING:", ev)
        post_event(ev)
