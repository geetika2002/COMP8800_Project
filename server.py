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

from database import SessionLocal, init_db
from model import Event as DBEvent

load_dotenv()
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

# Use two models: fast one for interactive shell, stronger one for analysis
OLLAMA_MODEL_SHELL = os.getenv("OLLAMA_MODEL_SHELL", "phi3:mini")
OLLAMA_MODEL_ANALYSIS = os.getenv("OLLAMA_MODEL_ANALYSIS", "llama3.1:8b")

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

ANALYSIS_USER_INSTRUCTIONS = (
    "Return your answer between <JSON> and </JSON> tags. "
    "Inside the tags, output ONLY a JSON object with keys: "
    "summary, intent, risk_score, explanation."
)

def ollama_chat(model: str, system: str, user: str, *, num_predict: int, temperature: float, timeout_s: int) -> str:
    r = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": {"temperature": temperature, "num_predict": num_predict},
        },
        timeout=timeout_s,
    )
    r.raise_for_status()
    return (r.json().get("message") or {}).get("content", "").strip()

def safe_json_or_wrap(text: str) -> str:
    """
    Prefer extracting JSON from <JSON>...</JSON>.
    If that fails, try raw JSON.
    Otherwise wrap into a fallback JSON object.
    """
    if not text:
        return ""

    # 1) Extract JSON between tags
    m = re.search(r"<JSON>\s*(\{.*?\})\s*</JSON>", text, flags=re.DOTALL)
    if m:
        candidate = m.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except Exception:
            pass

    # 2) Try parsing the whole response as JSON
    try:
        json.loads(text)
        return text
    except Exception:
        return json.dumps({
            "summary": "Non-JSON model output",
            "intent": "other",
            "risk_score": 5,
            "explanation": text[:500]
        })

def build_session_prompt(events: List[DBEvent]) -> str:
    """
    Build a single prompt summarizing the session's observed commands/events.
    """
    lines = []
    for e in events:
        ts = e.timestamp.isoformat() if isinstance(e.timestamp, datetime) else str(e.timestamp)
        cmd = e.command or ""
        meta = e.meta_data or ""
        if cmd:
            lines.append(f"[{ts}] CMD: {cmd}")
        elif meta:
            lines.append(f"[{ts}] META: {meta[:200]}")
    blob = "\n".join(lines)
    return f"Observed session activity:\n{blob}\n\n{ANALYSIS_USER_INSTRUCTIONS}"

# -----------------------------
# Background analysis functions
# -----------------------------

def analyze_event_or_session_background(event_id: str, timeout_s: int = 180):
    """
    Non-blocking background task:
    - If event has a session_id: analyze the whole session and write result to all events in that session
    - Else: analyze this one event
    """
    db = SessionLocal()
    try:
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

            prompt = build_session_prompt(session_events)

            try:
                analysis_text = ollama_chat(
                    model=OLLAMA_MODEL_ANALYSIS,
                    system=SOC_SYSTEM,
                    user=prompt,
                    num_predict=220,
                    temperature=0.1,
                    timeout_s=timeout_s,
                )
                analysis_text = safe_json_or_wrap(analysis_text)
            except Exception as e:
                print("Background session analysis error:", e)
                return

            for e in session_events:
                e.llm_analysis = analysis_text
            db.commit()
            return

        # No session_id: analyze single event command if present
        if not ev.command:
            return

        prompt = f"Observed commands: {ev.command}\n{ANALYSIS_USER_INSTRUCTIONS}"

        try:
            analysis_text = ollama_chat(
                model=OLLAMA_MODEL_ANALYSIS,
                system=SOC_SYSTEM,
                user=prompt,
                num_predict=160,
                temperature=0.1,
                timeout_s=timeout_s,
            )
            ev.llm_analysis = safe_json_or_wrap(analysis_text)
            db.commit()
        except Exception as e:
            print("Background single-event analysis error:", e)
            return

    finally:
        db.close()

# -----------------------------
# FastAPI app setup
# -----------------------------

app = FastAPI(on_startup=[init_db])

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # restrict later
    allow_methods=["*"],
    allow_headers=["*"],
)

# Input model for event ingestion
class EventIn(BaseModel):
    timestamp: Optional[str] = None
    session_id: Optional[str] = None
    src_ip: Optional[str] = None
    src_port: Optional[int] = None
    dest_service: Optional[str] = None
    username: Optional[str] = None
    command: Optional[str] = None
    meta_data: Optional[str] = None

class AnalyzeResult(BaseModel):
    analyzed: int
    updated_event_ids: List[str]

# POST: Ingest new event (FAST) + schedule analysis in the background
@app.post("/api/events", status_code=201)
def ingest(event: EventIn, background_tasks: BackgroundTasks):
    db = SessionLocal()
    try:
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
            llm_analysis=None,  # not set here
        )
        db.add(ev)
        db.commit()
        db.refresh(ev)

        # Only analyze when the session ends (1 analysis per session)
        cmd = (event.command or "").strip().lower()
        sid = (event.session_id or "").strip()

        if sid and cmd in ("exit", "logout", "quit"):
            background_tasks.add_task(analyze_event_or_session_background, ev.id, 180)

        return {"status": "ok", "id": ev.id}
    finally:
        db.close()

# GET: List events
@app.get("/api/events")
def list_events(limit: int = 999999):
    db = SessionLocal()
    try:
        events = (
            db.query(DBEvent)
            .order_by(DBEvent.timestamp.desc())
            .limit(limit)
            .all()
        )
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

# Manual: Analyze a whole session on-demand
@app.post("/api/analyze/session/{session_id}", response_model=AnalyzeResult)
def analyze_session(session_id: str, timeout_s: int = 180):
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
            )
            analysis_text = safe_json_or_wrap(analysis_text)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Local LLM analysis error: {e}")

        updated_ids = []
        for ev in events:
            ev.llm_analysis = analysis_text
            updated_ids.append(ev.id)

        db.commit()
        return AnalyzeResult(analyzed=len(updated_ids), updated_event_ids=updated_ids)

    finally:
        db.close()

# Manual: Analyze recent events missing analysis (batch)
@app.post("/api/analyze/recent", response_model=AnalyzeResult)
def analyze_recent(limit: int = 50, timeout_s: int = 180):
    db = SessionLocal()
    try:
        events = (
            db.query(DBEvent)
            .filter((DBEvent.llm_analysis == None))  # noqa: E711
            .order_by(DBEvent.timestamp.desc())
            .limit(limit)
            .all()
        )

        if not events:
            return AnalyzeResult(analyzed=0, updated_event_ids=[])

        updated_ids = []

        by_session = {}
        for e in events:
            sid = (e.session_id or "").strip()
            by_session.setdefault(sid, []).append(e)

        for sid, evs in by_session.items():
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
                        )
                        e.llm_analysis = safe_json_or_wrap(analysis_text)
                        updated_ids.append(e.id)
                    except Exception:
                        continue
                continue

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
                )
                analysis_text = safe_json_or_wrap(analysis_text)
            except Exception:
                continue

            batch_ids = {e.id for e in evs}
            for ev in session_events:
                if ev.id in batch_ids:
                    ev.llm_analysis = analysis_text
                    updated_ids.append(ev.id)

        db.commit()
        return AnalyzeResult(analyzed=len(updated_ids), updated_event_ids=updated_ids)

    finally:
        db.close()

@app.post("/api/respond")
def respond(payload: dict):
    cmd = payload.get("command", "")
    if not cmd:
        raise HTTPException(status_code=400, detail="Missing command")

    cmd = cmd.replace("\x1b", "")[:1000]

    shell_system = (
        "You are emulating a Linux shell inside an SSH honeypot. "
        "Return ONLY the exact stdout/stderr of the command. "
        "Do not ask questions. Do not add commentary. "
        "Do not mention being an AI. "
        "Do not add extra sentences. "
        "If the command has no output, return an empty line."
    )

    try:
        output = ollama_chat(
            model=OLLAMA_MODEL_SHELL,
            system=shell_system,
            user=cmd,
            num_predict=60,
            temperature=0.2,
            timeout_s=25,
        )
        if not output:
            output = "\n"
        elif not output.endswith("\n"):
            output += "\n"

    except Exception as e:
        print("Ollama error:", e)
        output = "(AI unavailable)\n"

    return {"response": output}