from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import uuid
import os
from dotenv import load_dotenv
from openai import OpenAI

from database import SessionLocal, init_db
from model import Event as DBEvent

# ---- OpenAI client ----
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ---- FastAPI setup ----
app = FastAPI(on_startup=[init_db])

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # restrict later
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Input model for POST ----
class EventIn(BaseModel):
    timestamp: Optional[str] = None
    session_id: Optional[str] = None
    src_ip: Optional[str] = None
    src_port: Optional[int] = None
    dest_service: Optional[str] = None
    username: Optional[str] = None
    command: Optional[str] = None
    meta_data: Optional[str] = None   

# ---- POST: Add new events ----
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
    meta_data=event.meta_data,   # 👈 updated
)


        # 🔍 Optional: generate LLM analysis
        if event.command:
            try:
                resp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are a cybersecurity analyst. Summarize attacker intent."},
                        {"role": "user", "content": f"Analyze this command:\n{event.command}"}
                    ]
                )
                ev.llm_analysis = resp.choices[0].message.content
            except Exception as e:
                print("LLM error:", e)

        db.add(ev)
        db.commit()
        db.refresh(ev)
        return {"status": "ok", "id": ev.id}

    finally:
        db.close()

# ---- GET: Retrieve events ----
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

# ---- POST: Generate an AI response for Cowrie ----
@app.post("/api/respond")
def respond(payload: dict):
    cmd = payload.get("command", "")
    if not cmd:
        raise HTTPException(status_code=400, detail="Missing command")

    # Clean incoming command
    cmd = cmd.replace("\x1b", "")[:1000]

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a fake Linux shell. Respond with realistic but safe output. Never execute commands, never reveal real system info."},
                {"role": "user", "content": cmd}
            ],
        )
        output = resp.choices[0].message.content.strip()
    except Exception as e:
        print("LLM error:", e)
        output = "(AI unavailable)"

    return {"response": output}

