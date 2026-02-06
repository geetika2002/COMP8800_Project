import os
import json
import time
import uuid
import requests

# ---- CONFIG ----
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.environ.get("OLLAMA_MODEL", "phi3:mini")

DEBUG = True
DEBUG_LOG = "logs/llm_debug.jsonl"

os.makedirs("logs", exist_ok=True)


def _log_debug(entry: dict):
    if not DEBUG:
        return
    with open(DEBUG_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def analyze_logs(log_text: str, session_id: str | None = None) -> str:
    """
    Milestone 3 version of analyze_logs.
    Uses local Ollama + records automatic debug trace.
    """
    session_id = session_id or str(uuid.uuid4())
    start = time.time()

    debug_entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "session_id": session_id,
        "provider": "ollama",
        "model": MODEL,
        "llm_called": False,
        "command_log": log_text,
        "backend_status": None,
        "response": None,
        "latency_ms": None,
    }

    try:
        debug_entry["llm_called"] = True

        r = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": MODEL,
                "stream": False,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a cybersecurity analyst. Summarize attacker intent."
                    },
                    {
                        "role": "user",
                        "content": f"Here are the commands:\n{log_text}"
                    }
                ],
            },
            timeout=20,
        )

        r.raise_for_status()
        data = r.json()

        response_text = data["message"]["content"]

        debug_entry["backend_status"] = "ok"
        debug_entry["response"] = response_text
        debug_entry["latency_ms"] = int((time.time() - start) * 1000)

        _log_debug(debug_entry)
        return response_text

    except Exception as e:
        debug_entry["backend_status"] = "error"
        debug_entry["response"] = "-bash: AI backend unavailable"
        debug_entry["error"] = str(e)
        debug_entry["latency_ms"] = int((time.time() - start) * 1000)

        _log_debug(debug_entry)
        return "-bash: AI backend unavailable"


if __name__ == "__main__":
    sample = "ls; whoami; cat /etc/passwd"
    print("\n--- MODEL OUTPUT ---\n")
    print(analyze_logs(sample))
