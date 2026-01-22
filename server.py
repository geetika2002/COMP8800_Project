from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import uuid
import os
from dotenv import load_dotenv
import requests
import json

from database import SessionLocal, init_db
from model import Event as DBEvent

load_dotenv()
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

# Use two models: fast one for interactive shell, stronger one for analysis
OLLAMA_MODEL_SHELL = os.getenv("OLLAMA_MODEL_SHELL", "phi3:mini")
OLLAMA_MODEL_ANALYSIS = os.getenv("OLLAMA_MODEL_ANALYSIS", "llama3.1:8b")

SOC_SYSTEM = (
    "You are a SOC analyst for a defensive SSH honeypot. "
    "You MUST output ONLY a single JSON object and nothing else "
    "(no markdown, no code fences, no explanation). "
    "If unsure, use intent=\"other\" and risk_score=5."
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


#FastAPI app setup
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

# POST: Ingest new event
@app.post("/api/events", status_code=201)
def ingest(event: EventIn):
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
)
        # Generate LLM analysis if command is present
        if event.command:
            try:
                user_prompt = (
                    f"Observed commands: {event.command}\n"
                    "Return ONLY JSON with keys: "
                    "summary (string, under 25 words), "
                    "intent (one of: recon, bruteforce, download, persistence, priv_esc, other), "
                    "risk_score (integer 0-10), "
                    "explanation (string, 2-4 sentences explaining the reasoning)."

                )

                analysis_text = ollama_chat(
                    model=OLLAMA_MODEL_ANALYSIS,
                    system=SOC_SYSTEM,
                    user=user_prompt,
                    num_predict=160,
                    temperature=0.1,
                    timeout_s=60,
                )

                # Store the JSON string directly (keeps your DB schema unchanged)
                ev.llm_analysis = analysis_text

            except Exception as e:
                print("Local LLM analysis error:", e)
                ev.llm_analysis = None


        db.add(ev)
        db.commit()
        db.refresh(ev)
        return {"status": "ok", "id": ev.id}

    finally:
        db.close()

# GET : List events
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
            num_predict=60,       # keep short for speed
            temperature=0.2,
            timeout_s=25,
        )

        if not output:
            output = "\n"
        elif not output.endswith("\n"):
            output += "\n"


    except Exception as e:
        print("Ollama error:", e)
        output = "(AI unavailable)"

    return {"response": output}

