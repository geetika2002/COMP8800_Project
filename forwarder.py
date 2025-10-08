# forwarder.py
import subprocess
import requests
import time
from datetime import datetime
import re
import sys

COLLECTOR = "http://127.0.0.1:8000/api/events"
DOCKER_CONTAINER = "cowrie"

proc = subprocess.Popen(
    ["docker", "logs", "-f", DOCKER_CONTAINER],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    bufsize=1
)

# Patterns seen in your logs
cmd_re = re.compile(r"\] .*CMD:\s*(.+)$")
found_re = re.compile(r"Command found:\s*(.+)$")
ip_re = re.compile(r"(\d+\.\d+\.\d+\.\d+)")

def extract_ip(line):
    m = ip_re.search(line)
    return m.group(1) if m else "unknown"

def parse_line(line):
    """
    Return an event dict if the line contains relevant info, otherwise None.
    """
    line = line.strip()
    # Match "CMD: <command>"
    m = cmd_re.search(line)
    if m:
        command = m.group(1).strip()
        return {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "session_id": None,
            "src_ip": extract_ip(line),
            "src_port": None,
            "dest_service": "ssh",
            "username": None,
            "command": command,
            "metadata": line
        }

    # Match "Command found: <command>" (some versions/log lines)
    m = found_re.search(line)
    if m:
        command = m.group(1).strip()
        return {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "session_id": None,
            "src_ip": extract_ip(line),
            "src_port": None,
            "dest_service": "ssh",
            "username": None,
            "command": command,
            "metadata": line
        }

    # Optionally catch login attempts (if you want)
    if "unauthorized login" in line or "login attempt" in line.lower():
        return {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "session_id": None,
            "src_ip": extract_ip(line),
            "src_port": None,
            "dest_service": "ssh",
            "username": None,
            "command": "login_attempt",
            "metadata": line
        }

    return None

def post_event(ev):
    try:
        resp = requests.post(COLLECTOR, json=ev, timeout=5)
        print(f"POST -> {resp.status_code} {resp.reason} | id={resp.json().get('id') if resp.status_code in (200,201) else 'n/a'}")
    except Exception as e:
        print("Failed to POST:", e, file=sys.stderr)

print("Forwarder started, following container:", DOCKER_CONTAINER)
while True:
    line = proc.stdout.readline()
    if not line:
        time.sleep(0.1)
        continue
    # debug: show raw line
    print("RAW:", line.strip())
    ev = parse_line(line)
    if ev:
        print("POSTING:", ev)
        post_event(ev)
