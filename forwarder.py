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

# Patterns seen in logs
cmd_re = re.compile(r"\] .*CMD:\s*(.+)$")
found_re = re.compile(r"Command found:\s*(.+)$")
ip_re = re.compile(r"(\d+\.\d+\.\d+\.\d+)")

# Cowrie "New connection" line contains the real session id:
# ... New connection: 127.0.0.1:36504 (127.0.0.1:2222) [session: f3aa5f7d7317]
new_conn_re = re.compile(r"New connection:\s+(\d+\.\d+\.\d+\.\d+):\d+.*\[\s*session:\s*([a-f0-9]+)\s*\]")

# Keep latest session_id per src_ip (good enough for localhost testing)
ip_to_session = {}

def extract_ip(line: str) -> str:
    m = ip_re.search(line)
    return m.group(1) if m else "unknown"

def learn_session_mapping(line: str):
    """
    Update ip_to_session when we see a 'New connection' line.
    """
    m = new_conn_re.search(line)
    if not m:
        return
    ip, sid = m.group(1), m.group(2)
    ip_to_session[ip] = sid
    print(f"LEARNED SESSION: ip={ip} session_id={sid}")

def current_session_id_for(line: str):
    ip = extract_ip(line)
    return ip_to_session.get(ip)

def parse_line(line: str):
    """
    Return an event dict if the line contains relevant info, otherwise None.
    """
    line = line.strip()

    # Learn mapping if this is a new connection line
    learn_session_mapping(line)

    # Match "CMD: <command>"
    m = cmd_re.search(line)
    if m:
        command = m.group(1).strip()
        return {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "session_id": current_session_id_for(line),
            "src_ip": extract_ip(line),
            "src_port": None,
            "dest_service": "ssh",
            "username": None,
            "command": command,
            "meta_data": line
        }

    # Match "Command found: <command>" (some versions/log lines)
    m = found_re.search(line)
    if m:
        command = m.group(1).strip()
        return {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "session_id": current_session_id_for(line),
            "src_ip": extract_ip(line),
            "src_port": None,
            "dest_service": "ssh",
            "username": None,
            "command": command,
            "meta_data": line
        }

    if "unauthorized login" in line.lower() or "login attempt" in line.lower():
        return {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "session_id": current_session_id_for(line),
            "src_ip": extract_ip(line),
            "src_port": None,
            "dest_service": "ssh",
            "username": None,
            "command": "login_attempt",
            "meta_data": line
        }

    return None

def post_event(ev):
    try:
        # Bump timeout: your /api/events can do LLM analysis; 5s may be too short
        resp = requests.post(COLLECTOR, json=ev, timeout=20)
        if resp.status_code in (200, 201):
            rid = resp.json().get("id")
        else:
            rid = "n/a"
        print(f"POST -> {resp.status_code} {resp.reason} | id={rid} | session_id={ev.get('session_id')}")
    except Exception as e:
        print("Failed to POST:", e, file=sys.stderr)

print("Forwarder started, following container:", DOCKER_CONTAINER)

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
