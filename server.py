# server.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
import uuid
from datetime import datetime

DB = "events.db"
#test comment
def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS events (
                 id TEXT PRIMARY KEY,
                 timestamp TEXT,
                 session_id TEXT,
                 src_ip TEXT,
                 src_port INTEGER,
                 dest_service TEXT,
                 username TEXT,
                 command TEXT,
                 metadata TEXT
                 )""")
    conn.commit()
    conn.close()

app = FastAPI(on_startup=[init_db])

class Event(BaseModel):
    timestamp: Optional[str] = None
    session_id: Optional[str] = None
    src_ip: Optional[str] = None
    src_port: Optional[int] = None
    dest_service: Optional[str] = None
    username: Optional[str] = None
    command: Optional[str] = None
    metadata: Optional[str] = None  # change from dict -> str

@app.post("/api/events", status_code=201)
def ingest(event: Event):
    ev = event.dict()
    ev_id = str(uuid.uuid4())
    ts = ev.get("timestamp") or datetime.utcnow().isoformat() + "Z"
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""INSERT INTO events (id,timestamp,session_id,src_ip,src_port,dest_service,username,command,metadata)
                 VALUES (?,?,?,?,?,?,?,?,?)""",
              (ev_id, ts, ev.get("session_id"), ev.get("src_ip"), ev.get("src_port"),
               ev.get("dest_service"), ev.get("username"), ev.get("command"), str(ev.get("metadata"))))
    conn.commit()
    conn.close()
    return {"status": "ok", "id": ev_id}

@app.get("/api/events")
def list_events(limit: int = 100):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT id,timestamp,session_id,src_ip,src_port,dest_service,username,command,metadata FROM events ORDER BY timestamp DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    keys = ["id","timestamp","session_id","src_ip","src_port","dest_service","username","command","metadata"]
    return [dict(zip(keys, r)) for r in rows]
