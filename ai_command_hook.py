# ai_command_hook.py
# Minimal Cowrie handler: when a command arrives, call our backend and print the reply.
# Place this file in Cowrie's commands directory.

import requests
import time

# small canned responses to avoid calling API for very common commands
FAKE_RESPONSES = {
    "ls": "bin  etc  home  usr",
    "whoami": "root",
    "pwd": "/root",
    "uname": "Linux honeypot 5.4.0"
}

API_URL = "http://127.0.0.1:8000/api/respond"  # see note below about networking
# Alternative if using same docker network: "http://<fastapi_container_name>:8000/api/respond"

def get_ai_response(command_text):
    cmd_key = command_text.strip().split()[0] if command_text.strip() else ""
    # return quick canned response if matched
    if cmd_key in FAKE_RESPONSES:
        return FAKE_RESPONSES[cmd_key]

    try:
        r = requests.post(API_URL, json={"command": command_text}, timeout=3)
        if r.status_code == 200:
            return r.json().get("response", "(no response)")
        else:
            return "(ai error)"
    except Exception as e:
        # keep fallback very simple
        return "(system unavailable)"

# Cowrie will expect a method or function to be invoked when commands occur.
# How you hook this into Cowrie depends on exact version; simplest approach: have the existing handler call get_ai_response()
# and write the returned text to the terminal session.
#
# Example: in the place Cowrie handles an incoming command, do:
#
#   reply = get_ai_response(cmd)
#   session.write(reply + "\n")
#
# Exactly how to call session.write depends on local handler APIs; in many places you can call `self.write()` or `protocol.write()`.
