from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import uuid
import os
from dotenv import load_dotenv

import requests
import json
import re
import time
from pathlib import Path
from database import SessionLocal, init_db
from model import Event as DBEvent

import ipaddress
from typing import Dict, Any

# -----------------------------
# Environment / Ollama settings
# -----------------------------

# Load values from .env into os.environ
load_dotenv()

# Base URL for Ollama server (defaults to local install)
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

# Use two models:
# - Shell model: fast/cheap for interactive fake terminal responses
# - Analysis model: stronger for SOC-style classification
OLLAMA_MODEL_SHELL = os.getenv("OLLAMA_MODEL_SHELL", "phi3:mini")
OLLAMA_MODEL_ANALYSIS = os.getenv("OLLAMA_MODEL_ANALYSIS", "llama3.1:8b")

# -----------------------------
# LLM debug logging (JSONL)
# -----------------------------

# Turn on by setting LLM_DEBUG=1 in environment/.env
LLM_DEBUG = os.getenv("LLM_DEBUG", "0") == "1"

# Store one JSON object per line for easy grep + later analysis
LLM_DEBUG_PATH = os.getenv("LLM_DEBUG_PATH", "logs/llm_debug.jsonl")

# Ensure logs/ exists
Path("logs").mkdir(exist_ok=True)

def llm_debug_log(entry: dict) -> None:
    """
    Append a single JSON record (one line) to logs/llm_debug.jsonl
    when LLM_DEBUG=1 is set.
    """
    if not LLM_DEBUG:
        return

    # JSONL format: each line is a valid JSON object
    with open(LLM_DEBUG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

# -----------------------------
# Prompt templates
# -----------------------------

# System prompt: enforces strict structure and intent taxonomy
SOC_SYSTEM = (
    "You are a SOC analyst for a defensive SSH honeypot. "
    "Output your answer ONLY between <JSON> and </JSON> tags. "
    "Inside the tags, output a single valid JSON object with the following keys exactly: "
    "summary (string, under 25 words), "
    "intent (one of: recon, bruteforce, download, persistence, priv_esc, other), "
    "risk_score (integer from 0 to 10), "
    "explanation (2 to 4 sentences explaining the reasoning). "
    "No markdown, no code fences, no extra text outside the tags. "
    "If unsure, set intent=\"other\" and risk_score=5."
)

# Extra instructions appended to prompts (helps models stay strict)
ANALYSIS_USER_INSTRUCTIONS = (
    "Return your answer between <JSON> and </JSON> tags. "
    "Inside the tags, output ONLY a JSON object with keys: "
    "summary, intent, risk_score, explanation."
)

# -----------------------------
# Centralized Ollama call path
# -----------------------------

def ollama_chat(
    model: str,
    system: str,
    user: str,
    *,
    num_predict: int,
    temperature: float,
    timeout_s: int,
    route: str = "unknown",
    session_id: str = "",
) -> str:
    """
    Single choke-point for ALL LLM calls (shell + analysis).
    When LLM_DEBUG=1, logs a JSONL record per call.

    route is a small label you set so later you can tell which API path
    triggered the request (shell vs background vs manual analysis).
    """
    t0 = time.time()

    try:
        # Call Ollama chat endpoint (non-streaming)
        r = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "options": {
                    "temperature": temperature,
                    "num_predict": num_predict,
                },
            },
            timeout=timeout_s,
        )

        # Raise for HTTP errors (4xx/5xx)
        r.raise_for_status()

        # Ollama response structure: {"message": {"content": "..."}}
        out = (r.json().get("message") or {}).get("content", "").strip()

        # Debug record for observability (latency/prompt preview/etc.)
        llm_debug_log({
            "ts": datetime.utcnow().isoformat() + "Z",
            "provider": "ollama",
            "model": model,
            "route": route,  # e.g., "shell", "analysis_session_bg", "analysis_session_manual"
            "session_id": (session_id or None),
            "num_predict": num_predict,
            "temperature": temperature,
            "timeout_s": timeout_s,
            "backend_status": "ok",
            "latency_ms": int((time.time() - t0) * 1000),
            "prompt_preview": user[:500],
            "response_preview": out[:500],
        })

        return out

    except Exception as e:
        # Log errors too (timeouts, connection errors, JSON parse failures, etc.)
        llm_debug_log({
            "ts": datetime.utcnow().isoformat() + "Z",
            "provider": "ollama",
            "model": model,
            "route": route,
            "session_id": (session_id or None),
            "num_predict": num_predict,
            "temperature": temperature,
            "timeout_s": timeout_s,
            "backend_status": "error",
            "error": repr(e),
            "latency_ms": int((time.time() - t0) * 1000),
            "prompt_preview": user[:500],
        })
        raise

# -----------------------------
# LLM response parsing helpers
# -----------------------------

def safe_json_or_wrap(text: str) -> str:
    """
    Prefer extracting JSON from <JSON>...</JSON>.
    If that fails, try raw JSON.
    Otherwise wrap into a fallback JSON object.

    Returns: a JSON *string* that can be stored in DB (llm_analysis column).
    """
    if not text:
        return ""

    # 1) Extract JSON object between <JSON> tags
    m = re.search(r"<JSON>\s*(\{.*?\})\s*</JSON>", text, flags=re.DOTALL)
    if m:
        candidate = m.group(1).strip()
        try:
            json.loads(candidate)  # validate JSON
            return candidate
        except Exception:
            pass

    # 2) Try treating the entire response as JSON
    try:
        json.loads(text)
        return text
    except Exception:
        # 3) Fallback: store model output inside "explanation"
        return json.dumps({
            "summary": "Non-JSON model output",
            "intent": "other",
            "risk_score": 5,
            "explanation": text[:500]
        })


def strip_markdown_fences(text: str) -> str:
    """
    Remove ``` or ```bash fences if the model wraps shell output in markdown.
    Keeps only raw stdout/stderr-style text so it feels like a real terminal.
    """
    if not text:
        return text

    t = text.strip()

    # Remove opening fence (``` or ```bash)
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", t)

    # Remove closing fence
    if t.endswith("```"):
        t = re.sub(r"\n?```$", "", t)

    # Normalize to trailing newline (terminal-like)
    return t.rstrip() + "\n"




def normalize_shell_output(cmd: str, output: str) -> str:
    """
    Normalize obviously non-shell, assistant-like, or malformed model output
    into short Linux-style terminal responses.
    """
    clean_cmd = (cmd or "").strip()
    out = strip_markdown_fences(output or "").strip()
    lowered = out.lower()

    invalid_markers = [
        "please enter a valid command",
        "invalid command",
        "unknown command",
        "check your permissions and try again",
        "command result transcription",
        "transcript ends here",
        "as an ai",
    ]

    is_simple_command = bool(re.fullmatch(r"[A-Za-z0-9._/+:-]+", clean_cmd))

    if any(marker in lowered for marker in invalid_markers):
        if is_simple_command:
            return f"bash: {clean_cmd}: command not found\n"
        return "bash: syntax error near unexpected token `newline'\n"

    if is_simple_command and lowered in {"permission denied", "permission denied."}:
        return f"bash: {clean_cmd}: command not found\n"

    if not out:
        return "\n"

    return out.rstrip() + "\n"

# -----------------------------
# Prompt building for sessions
# -----------------------------

def build_session_prompt(events: List[DBEvent]) -> str:
    """
    Build a single prompt summarizing the session's observed commands/events.

    Why session-level?
    - Better context → more accurate intent/risk
    - Fewer LLM calls (one analysis per session instead of per command)
    """
    lines = []

    # Turn each event into a readable timeline line
    for e in events:
        ts = e.timestamp.isoformat() if isinstance(e.timestamp, datetime) else str(e.timestamp)
        cmd = e.command or ""
        meta = e.meta_data or ""

        if cmd:
            lines.append(f"[{ts}] CMD: {cmd}")
        elif meta:
            # Truncate metadata so prompts don’t explode
            lines.append(f"[{ts}] META: {meta[:200]}")

    blob = "\n".join(lines)

    # Append format constraints so output is machine-parseable
    return f"Observed session activity:\n{blob}\n\n{ANALYSIS_USER_INSTRUCTIONS}"

# -----------------------------
# Background analysis functions
# -----------------------------

def analyze_event_or_session_background(event_id: str, timeout_s: int = 180):
    """
    Non-blocking background task:

    - If event has a session_id:
        analyze the whole session and write ONE shared result to all events in that session.
    - Else:
        analyze only this one event.

    This runs after ingestion so the ingest endpoint stays fast.
    """
    db = SessionLocal()
    try:
        # Fetch the triggering event
        ev = db.query(DBEvent).filter(DBEvent.id == event_id).first()
        if not ev:
            return

        sid = (ev.session_id or "").strip()

        # If we have a session_id, analyze the whole session (better quality + fewer calls)
        if sid:
            session_events = (
                db.query(DBEvent)
                .filter(DBEvent.session_id == sid)
                .order_by(DBEvent.timestamp.asc())
                .all()
            )
            if not session_events:
                return

            # Build a full timeline prompt
            prompt = build_session_prompt(session_events)

            try:
                # Call stronger model for SOC classification + risk scoring
                analysis_text = ollama_chat(
                    model=OLLAMA_MODEL_ANALYSIS,
                    system=SOC_SYSTEM,
                    user=prompt,
                    num_predict=220,
                    temperature=0.1,
                    timeout_s=timeout_s,
                    route="analysis_session_bg",
                    session_id=sid,
                )

                # store valid JSON text
                analysis_text = safe_json_or_wrap(analysis_text)

            except Exception as e:
                # Avoid crashing background worker; just log and stop
                print("Background session analysis error:", e)
                return

            # Write the same analysis onto every event in that session
            for e in session_events:
                e.llm_analysis = analysis_text

            db.commit()
            return

        # No session_id: analyze single event command if present
        if not ev.command:
            return

        # Single-command prompt (less context, but still useful)
        prompt = f"Observed commands: {ev.command}\n{ANALYSIS_USER_INSTRUCTIONS}"

        try:
            analysis_text = ollama_chat(
                model=OLLAMA_MODEL_ANALYSIS,
                system=SOC_SYSTEM,
                user=prompt,
                num_predict=160,
                temperature=0.1,
                timeout_s=timeout_s,
                route="analysis_event_bg",
                session_id="",
            )

            ev.llm_analysis = safe_json_or_wrap(analysis_text)
            db.commit()

        except Exception as e:
            print("Background single-event analysis error:", e)
            return

    finally:
        # Always close the DB session (prevents connection leaks)
        db.close()


# -----------------------------
# FastAPI app setup
# -----------------------------

# Initialize DB on app startup (create tables, etc.)
app = FastAPI(on_startup=[init_db])

# Allow the frontend to call this API cross-origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: restrict later (e.g., to your React host)
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# Pydantic schemas
# -----------------------------

class EventIn(BaseModel):
    """
    Incoming event schema for /api/events ingestion.

    These fields map directly into your DBEvent row.
    timestamp is optional because you use datetime.utcnow() server-side.
    """
    timestamp: Optional[str] = None
    session_id: Optional[str] = None
    src_ip: Optional[str] = None
    src_port: Optional[int] = None
    dest_service: Optional[str] = None
    username: Optional[str] = None
    command: Optional[str] = None
    meta_data: Optional[str] = None


class AnalyzeResult(BaseModel):
    """
    Simple structured response for manual/batch analysis endpoints.
    """
    analyzed: int
    updated_event_ids: List[str]

# -----------------------------
# GeoIP lookup (simple + cached)
# -----------------------------

GEO_CACHE: Dict[str, Dict[str, Any]] = {}
GEO_TTL_S = 24 * 60 * 60  # 24 hours

def _is_public_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
        return not (addr.is_private or addr.is_loopback or addr.is_multicast or addr.is_reserved or addr.is_link_local)
    except Exception:
        return False

def geo_lookup_ip(ip: str) -> Dict[str, Any]:
    """
    Simple IP geolocation lookup with in-memory caching.
    Uses ip-api.com (no key) for quick milestone demo.
    """
    ip = (ip or "").strip()
    if not ip:
        raise HTTPException(status_code=400, detail="Missing ip")

    if not _is_public_ip(ip):
        # Honeypot is often hit by public IPs, but if you test locally you might see private ranges.
        return {
            "ip": ip,
            "ok": False,
            "reason": "Non-public or invalid IP (private/loopback/reserved).",
        }

    now = time.time()
    cached = GEO_CACHE.get(ip)
    if cached and (now - cached.get("_ts", 0)) < GEO_TTL_S:
        out = dict(cached)
        out.pop("_ts", None)
        return out

    # ip-api fields (keeps response small)
    url = f"http://ip-api.com/json/{ip}"
    params = {
        "fields": "status,message,country,regionName,city,lat,lon,isp,org,as,query"
    }

    try:
        r = requests.get(url, params=params, timeout=8)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Geo lookup failed: {e}")

    if data.get("status") != "success":
        return {
            "ip": ip,
            "ok": False,
            "reason": data.get("message") or "lookup failed",
        }

    out = {
        "ip": data.get("query", ip),
        "ok": True,
        "country": data.get("country"),
        "region": data.get("regionName"),
        "city": data.get("city"),
        "lat": data.get("lat"),
        "lon": data.get("lon"),
        "isp": data.get("isp"),
        "org": data.get("org"),
        "asn": data.get("as"),
    }

    GEO_CACHE[ip] = {**out, "_ts": now}
    return out

# -----------------------------
# API: Ingest events
# -----------------------------

@app.post("/api/events", status_code=201)
def ingest(event: EventIn, background_tasks: BackgroundTasks):
    """
    Ingest a new event into the database.

    Design choice:
    - Do NOT run analysis inline here (keeps endpoint fast)
    - Only schedule analysis when a session-ending command happens
      so you do 1 analysis per session.
    """
    db = SessionLocal()
    try:
        # Create DB row (server assigns id + timestamp)
        ev = DBEvent(
            id=str(uuid.uuid4()),
            timestamp=datetime.utcnow(),
            session_id=event.session_id,
            src_ip=event.src_ip,
            src_port=event.src_port,
            dest_service=event.dest_service,
            username=event.username,
            command=event.command,
            meta_data=event.meta_data,
            llm_analysis=None,  # analysis filled later
        )

        db.add(ev)
        db.commit()
        db.refresh(ev)

        # Only analyze when the session ends (one analysis per session)
        cmd = (event.command or "").strip().lower()
        sid = (event.session_id or "").strip()

        # If we detect the end of an SSH session, schedule background analysis
        if sid and cmd in ("exit", "logout", "quit"):
            background_tasks.add_task(analyze_event_or_session_background, ev.id, 180)

        return {"status": "ok", "id": ev.id}

    finally:
        db.close()


# -----------------------------
# API: List events
# -----------------------------

@app.get("/api/events")
def list_events(limit: int = 999999):
    """
    Return most recent events first, up to limit.
    Used by your dashboard to render tables.
    """
    db = SessionLocal()
    try:
        events = (
            db.query(DBEvent)
            .order_by(DBEvent.timestamp.desc())
            .limit(limit)
            .all()
        )

        # Convert ORM objects into JSON-serializable dicts
        return [
            {
                "id": e.id,
                "timestamp": e.timestamp,
                "session_id": e.session_id,
                "src_ip": e.src_ip,
                "src_port": e.src_port,
                "dest_service": e.dest_service,
                "username": e.username,
                "command": e.command,
                "meta_data": e.meta_data,
                "llm_analysis": e.llm_analysis,
            }
            for e in events
        ]

    finally:
        db.close()


@app.get("/api/geo")
def geo(ip: str):
    return geo_lookup_ip(ip)

# -----------------------------
# API: Manual session analysis
# -----------------------------

@app.post("/api/analyze/session/{session_id}", response_model=AnalyzeResult)
def analyze_session(session_id: str, timeout_s: int = 180):
    """
    On-demand endpoint to analyze a whole session.

    Writes ONE shared analysis onto all events in that session.
    """
    db = SessionLocal()
    try:
        events = (
            db.query(DBEvent)
            .filter(DBEvent.session_id == session_id)
            .order_by(DBEvent.timestamp.asc())
            .all()
        )

        if not events:
            raise HTTPException(status_code=404, detail="Session not found")

        prompt = build_session_prompt(events)

        try:
            analysis_text = ollama_chat(
                model=OLLAMA_MODEL_ANALYSIS,
                system=SOC_SYSTEM,
                user=prompt,
                num_predict=220,
                temperature=0.1,
                timeout_s=timeout_s,
                route="analysis_session_manual",
                session_id=session_id,
            )
            analysis_text = safe_json_or_wrap(analysis_text)

        except Exception as e:
            # Present as 502 since backend dependency failed
            raise HTTPException(status_code=502, detail=f"Local LLM analysis error: {e}")

        updated_ids = []

        # Apply same analysis to all session events
        for ev in events:
            ev.llm_analysis = analysis_text
            updated_ids.append(ev.id)

        db.commit()

        return AnalyzeResult(analyzed=len(updated_ids), updated_event_ids=updated_ids)

    finally:
        db.close()


# -----------------------------
# API: Batch analyze recent missing analysis
# -----------------------------

@app.post("/api/analyze/recent", response_model=AnalyzeResult)
def analyze_recent(limit: int = 50, timeout_s: int = 180):
    """
    Analyze recent events that are missing llm_analysis.

    Strategy:
    - Group events by session_id
    - For sessions: analyze the full session once
    - For events with no session_id: analyze each command individually
    """
    db = SessionLocal()
    try:
        # Pull recent events missing llm_analysis
        events = (
            db.query(DBEvent)
            .filter((DBEvent.llm_analysis == None))  # noqa: E711 (explicit None check)
            .order_by(DBEvent.timestamp.desc())
            .limit(limit)
            .all()
        )

        if not events:
            return AnalyzeResult(analyzed=0, updated_event_ids=[])

        updated_ids: List[str] = []

        # Group the missing-analysis events by session_id
        by_session = {}
        for e in events:
            sid = (e.session_id or "").strip()
            by_session.setdefault(sid, []).append(e)

        for sid, evs in by_session.items():
            # If no session_id, fall back to per-event analysis
            if not sid:
                for e in evs:
                    if not e.command:
                        continue

                    prompt = f"Observed commands: {e.command}\n{ANALYSIS_USER_INSTRUCTIONS}"

                    try:
                        analysis_text = ollama_chat(
                            model=OLLAMA_MODEL_ANALYSIS,
                            system=SOC_SYSTEM,
                            user=prompt,
                            num_predict=160,
                            temperature=0.1,
                            timeout_s=timeout_s,
                            route="analysis_event_batch",
                            session_id="",
                        )
                        e.llm_analysis = safe_json_or_wrap(analysis_text)
                        updated_ids.append(e.id)

                    except Exception:
                        # Skip failures so the batch keeps going
                        continue

                continue

            # For sessions: fetch the full session timeline
            session_events = (
                db.query(DBEvent)
                .filter(DBEvent.session_id == sid)
                .order_by(DBEvent.timestamp.asc())
                .all()
            )
            if not session_events:
                continue

            prompt = build_session_prompt(session_events)

            try:
                analysis_text = ollama_chat(
                    model=OLLAMA_MODEL_ANALYSIS,
                    system=SOC_SYSTEM,
                    user=prompt,
                    num_predict=220,
                    temperature=0.1,
                    timeout_s=timeout_s,
                    route="analysis_session_batch",
                    session_id=sid,
                )
                analysis_text = safe_json_or_wrap(analysis_text)

            except Exception:
                continue

            # Only update the subset of session events that were in "missing analysis" list
            batch_ids = {e.id for e in evs}
            for ev in session_events:
                if ev.id in batch_ids:
                    ev.llm_analysis = analysis_text
                    updated_ids.append(ev.id)

        db.commit()

        return AnalyzeResult(analyzed=len(updated_ids), updated_event_ids=updated_ids)

    finally:
        db.close()


# -----------------------------
# API: Fake shell respond endpoint
# -----------------------------

@app.post("/api/respond")
def respond(payload: dict):
    """
    Given a command string, return simulated stdout/stderr.

    This is used for the interactive honeypot "shell" experience,
    so the attacker sees plausible command output.
    """
    cmd = payload.get("command", "")
    if not cmd:
        raise HTTPException(status_code=400, detail="Missing command")

    sid = (payload.get("session_id") or "").strip()

    # Basic sanitation: strip ANSI escape char and cap length
    cmd = cmd.replace("", "")[:1000]
    stripped_cmd = cmd.strip()

    # Hard-handle symbol-only / malformed shell syntax before the LLM sees it
    if stripped_cmd and re.fullmatch(r"[^\w\s]+", stripped_cmd):
        return {"response": "bash: syntax error near unexpected token `;`\n"}

    shell_system = (
        "You are emulating a Linux shell inside an SSH honeypot. "
        "Return ONLY the exact stdout/stderr of the command. "
        "Do not explain anything. Do not mention being an AI. "
        "Do not add commentary, markdown, code fences, transcript markers, or labels. "
        "If the command produces no output, return an empty line.\n\n"
        "Environment:\n"
        "- Current user: admin\n"
        "- Hostname: srv-web-02\n"
        "- Operating system: Ubuntu 22.04-like Linux\n"
        "- Default working directory: /home/admin\n\n"
        "Command consistency rules:\n"
        "- If the user enters exactly 'ls', always return exactly:\n"
        "backup.sh  notes.txt  downloads  projects\n"
        "- If the user enters exactly 'pwd', always return exactly:\n"
        "/home/admin\n"
        "- If the user enters exactly 'whoami', always return exactly:\n"
        "admin\n"
        "- If the user enters exactly 'hostname', always return exactly:\n"
        "srv-web-02\n"
        "- If the user enters exactly 'uname -a', always return a realistic Linux uname string for srv-web-02.\n"
        "- If the user enters exactly 'cat /etc/passwd', always return a short realistic passwd file containing root, daemon, www-data, and admin.\n"
        "- If the user enters exactly 'cat /etc/shadow', return permission denied.\n\n"
        "Filesystem background:\n"
        "/home/admin contains: backup.sh, notes.txt, downloads, projects\n"
        "/home/admin/downloads contains: readme.txt\n"
        "/home/admin/projects contains: deploy.py, inventory.csv\n"
        "/etc contains: hostname, issue, passwd, shadow, ssh\n"
        "/etc/ssh contains: sshd_config\n"
        "/var/log contains: auth.log, syslog, kern.log\n\n"
        "General behavior rules:\n"
        "- For the commands listed above, keep the output identical every time.\n"
        "- For other commands, return short, realistic terminal output.\n"
        "- If a command is unknown, invalid, or nonsensical, return exactly in this format:\n"
        "bash: <command>: command not found\n"
        "- If a file exists but is not readable, return a realistic permission denied error.\n"
        "- If a path does not exist, return a realistic no such file or directory error.\n"
        "- Do not say 'please enter a valid command'.\n"
        "- Do not explain errors.\n"
        "- Never add transcript markers, labels, or extra commentary.\n"
    )

    try:
        output = ollama_chat(
            model=OLLAMA_MODEL_SHELL,
            system=shell_system,
            user=cmd,
            num_predict=60,
            temperature=0.2,
            timeout_s=25,
            route="shell",
            session_id=sid,
        )
        output = normalize_shell_output(cmd, output)

    except Exception as e:
        print("Ollama error:", e)
        output = "(AI unavailable)\n"

    return {"response": output}