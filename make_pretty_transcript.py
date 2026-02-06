import json
from datetime import datetime

INPUT = "logs/llm_debug.jsonl"
OUTPUT = "logs/llm_transcript.txt"

def pretty_json(j: str) -> str:
    try:
        obj = json.loads(j)
        return json.dumps(obj, indent=2)
    except Exception:
        return j

with open(INPUT, "r", encoding="utf-8") as f, open(OUTPUT, "w", encoding="utf-8") as out:
    for line in f:
        e = json.loads(line)

        ts = e.get("ts", "")
        model = e.get("model")
        route = e.get("route")
        sid = e.get("session_id")
        status = e.get("backend_status")

        out.write("=" * 60 + "\n")
        out.write(f"TIMESTAMP : {ts}\n")
        out.write(f"MODEL     : {model}\n")
        out.write(f"ROUTE     : {route}\n")
        if sid:
            out.write(f"SESSION   : {sid}\n")
        out.write(f"STATUS    : {status}\n\n")

        # Shell interaction
        if route == "shell":
            out.write("COMMAND:\n")
            out.write(e.get("prompt_preview", "").strip() + "\n\n")
            out.write("RESPONSE:\n")
            out.write(e.get("response_preview", "").strip() + "\n\n")

        # Analysis output
        else:
            out.write("ANALYSIS OUTPUT:\n")
            out.write(pretty_json(e.get("response_preview", "")) + "\n\n")

    out.write("=" * 60 + "\n")
