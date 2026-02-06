# AI-Driven Honeypot Data Collector

## Project Overview
This project is an AI-powered honeypot data collection and analysis system designed to capture, interpret, and visualize SSH attacker behavior in a controlled environment.

The system combines a traditional SSH honeypot with local Large Language Models (LLMs) to simulate realistic attacker interaction and perform post-session security analysis.

It integrates:

- **Cowrie (SSH honeypot)** for attacker interaction  
- **FastAPI backend** for event ingestion and orchestration  
- **Local LLMs (via Ollama)** for shell emulation and attacker-intent analysis  
- **Forwarder script** for log parsing and event forwarding  
- **SQLite** for persistent event storage  
- **React Dashboard** for visualization and session-level analysis  

---

## System Workflow
```text
(Attacker)
      │
      ▼
[Cowrie SSH Honeypot]
      │
      │  (LLM #1: Fake Shell Output)
      └──> FastAPI /api/respond → Local LLM (Ollama)
      │
      ▼
[Cowrie Container Logs]
      ▼
[forwarder.py]
      ▼
[FastAPI Collector /api/events]
      │
      │  (LLM #2: Session / Event Analysis)
      └──> Local LLM (Ollama) → analysis stored in DB
      ▼
[SQLite Database]
      ▼
[React Dashboard]
(Session summaries, risk scoring, command timelines)

```
---

## Tech Stack

### Backend
- Cowrie (Dockerized)
- Python 3.12
- FastAPI
- SQLite
- Uvicorn
- Requests
- Pydantic
- python-dotenv

### AI / LLM
- **Local LLMs via Ollama**
  - Lightweight model for interactive shell responses
  - Stronger model for attacker-intent and risk analysis 
- All inference runs locally (no external API dependancy)

### Frontend
- React (Vite)
- Recharts
- Node.js 20+

---

## Key Features

### 1. Realistic SSH Interaction
- Cowrie captures attacker commands.
- Commands are forwarded to FastAPI.
- A local LLM generates realistic but safe Linux shell output.
- Attackers experience a convincing interactive shell without real system access.

### 2. Session-Based Attacker Analysis
- Events are grouped by **Cowrie session ID**.
- Analysis is performed **once per session** (on logout/exit or manually).
- Each session receives:
  - Intent classification (e.g., recon, bruteforce, persistence)
  - Risk score (0–10)
  - Natural-language explanation
- The same analysis is attached to all events in that session.

### 3. Background & On-Demand Analysis
- Analysis runs asynchronously to keep ingestion fast.
- Manual endpoints allow:
  - Re-analyzing a full session
  - Batch-analyzing recent unanalyzed events

### 4. Visual Dashboard
The React dashboard provides:
- High-level statistics (event count, unique IPs, timelines)
- Charts:
  - Events over time
  - Top commands
  - Source IP distribution
- Session-centric table with:
  - Intent
  - Risk score
  - Color-coded triage (green/yellow/red)
- Click-through session detail view:
  - Full command timeline
  - LLM-generated analysis
  - Raw metadata

---

## Setup & Installation

### 1. Clone the repository
```bash
git clone <repo_url>
cd honeypot-collector
```
### 2. Create and activate a virtual environment
```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
.venv\Scripts\activate     # Windows
```
### 3. Install dependencies 
```bash
pip install fastapi[all] requests sqlite3 pydantic uvicorn
```
## Running the Program 
### 1. Start the FastAPI server
```bash
uvicorn server:app --reload
```
The server will be accessible at http://127.0.0.1:8000.

The FastAPI handles:
* /api/events → event ingestion 
* /api/respond → AI-generated fake shell output
* /api/analyze/session/{session_id} → manual session analysis 
* /api/analyze/recent → batch analysis

### 2. Start Cowrie honeypot in Docker 
```bash
docker run -d --name cowrie --network=host -v ~/cowrie_override/shell/honeypot.py:/cowrie/cowrie-git/src/cowrie/shell/honeypot.py cowrie/cowrie:latest
```
Port 2222 will simulate an SSH service.

The honepot.py file is one that is found within the docker container with cowrie in it. It has been uploaded with this code, so you can use the location on your own device to mount it when running the docker container. 

To view logs: 
```bash
docker logs -f cowrie
```
### 3. Run the forwarder script
The forwarder reads Cowrie logs, parses them, and sends JSON events to the server.
```bash
python forwarder.py
```
This MUST stay running for data to appear in the dashboard.

### 4. Verify database storage 
```bash
sqlite3 events.db
sqlite> select * from events;
```
Each event includes:
* timestamp
* session ID 
* source IP
* command/metadata
* LLM analysis (JSON)

### 5. Testing the Honeypot
```bash
ssh -p 2222 root@localhost
```
Try commands such as: 
* whoami
* ls
* pwd
* cat /etc/passwd

Expected behaviour: 
* Fake shell output returned via LLM 
* Commands logged, stored and later analyzed 
* Session analysis triggered on exit 

### 6. Start the React Dashboard
Frontend source code is in: dashboard/
```bash
cd dashboard
npm install 
npm run dev 
```
Open the provided localhost URL to view:

* Event statistics 
* Charts and trends
* Session list with risk coloring
* Detailed per-session analysis 

## LLM Features

### AI-Powered Fake Shell Responses
- Cowrie intercepts attacker commands.
- Commands are forwarded to FastAPI via `/api/respond`.
- A **local LLM (via Ollama)** generates realistic but safe Linux shell output.
- This creates a convincing interactive SSH experience without exposing a real system.

### Attacker-Intent Analysis Stored in the Database
When `forwarder.py` posts events to the backend:
- FastAPI groups events by **session ID**.
- A local LLM performs attacker-intent analysis (session-level or event-level).
- The LLM produces:
  - Intent classification
  - Risk score
  - Natural-language explanation
- The analysis result is stored in **SQLite** and attached to relevant events.
- The React dashboard retrieves and displays this analysis.
---

## Future Work

1. **Security and Isolation**
   - Harden Docker containers
   - Sandbox LLM execution
   - Add rate limiting and abuse detection

2. **Improved Analysis Accuracy**
   - Refine intent categories and risk scoring
   - Better handling of noisy or incomplete sessions

3. **Dashboard Enhancements**
   - Severity-based filtering and search
   - Expandable analysis cards
   - Real-time event streaming
   - Session comparison and trend views

4. **Deployment Improvements**
   - Docker Compose for full-stack orchestration
   - Environment-based configuration (dev vs prod)
---
## Notes
- `forwarder.py` must run continuously while Cowrie is active.
- All LLM inference is performed **locally**; no external API keys are required.
- If Docker reports container conflicts, remove old containers:
  ```bash
  docker rm -f cowrie
