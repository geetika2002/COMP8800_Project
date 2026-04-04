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

# System Workflow

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
      │  (LLM #2: Session Analysis)
      └──> Local LLM (Ollama) → analysis stored in DB
      ▼
[SQLite Database]
      ▼
[React Dashboard]
      │
      ├── Session analysis view
      ├── Command timeline visualization
      ├── Dashboard statistics and charts
      └── IP geolocation lookup

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
Cowrie captures attacker commands during an SSH session.

Commands are forwarded to the FastAPI backend where a local LLM generates realistic Linux shell output.

This allows attackers to interact with what appears to be a real Linux environment while keeping the host system fully isolated.

Key behavior:
* Commands are intercepted and sent to /api/respond
* A local LLM generates plausible shell output
* Output is returned to Cowrie and shown to the attacker

The environment simulates a Linux server with realistic directories, users, and command responses.

### 2. Session-Based Attacker Analysis
Events are grouped by Cowrie session ID.

Instead of analyzing each command individually, the system performs one analysis per session to improve context and reduce LLM calls.

Each session receives:

* Intent classification (recon, bruteforce, download, persistence, priv_esc, other)
* Risk score (0–10)
* Natural language explanation of attacker behavior

The analysis result is stored as structured JSON in the database and attached to all events belonging to that session.

This allows the dashboard to quickly display attacker intent without re-running analysis.
### 3. Background & On-Demand Analysis
Analysis is designed to run asynchronously so event ingestion remains fast.

Two mechanisms are available:

1. Automatic Analysis: Session analysis automatically triggers when the honeypot detects commands such as: exit, logout, quit. 

2. Manual Analysis: The API also exposes endpoints to run analysis manually.


### 4. Visual Dashboard
The React dashboard provides an investigation interface for honeypot activity.

The dashboard displays key system metrics:

* Total sessions observed
* Unique attacking IP addresses
* Timestamp of the most recent event

Interactive navigation is supported:

* Clicking Total Sessions opens a full event table
* Clicking Unique IPs opens an IP activity table
* Charts

The dashboard visualizes honeypot activity using:

* Events over time
* Most frequently executed commands
* Source IP distribution

These charts help identify trends in attacker behavior.

Session Table:

* Session ID
* Detected attacker intent
* Risk score
* Top commands executed
* AI-generated summary
* Session start time
* Session end time
* Session duration
* Source IP address
* Number of events

Sessions are color-coded for quick triage:

* Green → low-risk or unknown activity
* Yellow → reconnaissance behavior
* Red → active attack behavior (privilege escalation, persistence, downloads)

Clicking a session opens a detailed investigation view.

### 5. Activity Timeline

The session detail view includes an **activity timeline** that visualizes attacker behavior during the session.

Each command is categorized using **regex-based classification rules**.

Examples of command types detected:

- Reconnaissance commands (`whoami`, `uname`, `hostname`)
- File download tools (`wget`, `curl`)
- Privilege escalation attempts (`sudo`, `su`)
- Persistence mechanisms (`crontab`, `systemctl`)
- Destructive commands (`rm -rf`, `dd`)

Commands are grouped into phases:

- **Recon Phase**
- **Action Phase**
- **Exit Phase**
- **General Activity**

The timeline displays:

- Command execution order
- Command classification badges
- Phase transitions
- Idle time gaps between commands

Idle gaps help analysts infer attacker behavior, such as:

- Uploading malware
- Reviewing files
- Running automated scripts


### 6. IP Geolocation

The dashboard supports **geolocation lookup for attacker IP addresses**.

When a source IP is clicked:

1. The React dashboard calls the FastAPI backend (`/api/geo`)
2. The backend queries the `ip-api.com` geolocation service
3. Location data is returned as JSON
4. The dashboard renders the location using an embedded **OpenStreetMap** view

Displayed information includes:

- Country
- Region
- City
- ISP / Organization
- Autonomous System Number (ASN)
- Approximate map location

Geolocation results are cached for **24 hours** to reduce repeated API requests.

> **Note:** Geolocation only works with **public IP addresses**. Private or localhost IPs cannot be resolved.

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

All AI-generated responses are simulated and do not execute real system commands, ensuring the honeypot remains fully isolated and safe.

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

### AI Fine-Tuning Experimentation

A custom dataset was generated from real honeypot sessions and used to fine-tune a smaller language model using LoRA.

Results:
- Improved structured JSON output consistency
- Better domain-specific alignment
- Larger pretrained models still outperformed in reasoning and accuracy

This highlights a trade-off between efficiency and performance when using local models.

#### Dataset Preparation

A custom dataset was created from real Cowrie honeypot sessions to support fine-tuning.

The dataset pipeline included:

- Raw session extraction (`raw_sessions.jsonl`)
- Initial labeling with structured outputs (`labeled_sessions_firstpass.jsonl`)
- Dataset balancing to reduce class bias (`train_balanced.jsonl`)
- Train / validation / test split:
  - Training set (`train_v2.jsonl`)
  - Validation set (`valid_v2.jsonl`)
  - Test set (`test_v2.jsonl`)

Only the training dataset was used to update model weights, while validation and test sets were used for evaluation and generalization.

Each entry follows an instruction-based format:
- Input: attacker command sequence  
- Output: structured JSON (summary, intent, risk score, explanation)
---
## Final Evaluation (Completed)

- End-to-end testing of full pipeline (Cowrie → forwarder → FastAPI → database → dashboard)
- Fixed dashboard issues (command frequency chart + duplicate login events)
- Validated system behavior under normal and edge-case scenarios
- Evaluated AI model performance and consistency

## Potential Future Work

If this project is ever worked on in the future, key characteristics to work on can include: 

- Expand dataset for improved fine-tuning
- Improve LLM reasoning for edge cases
- Optional Docker Compose orchestration
- Cloud deployment for real-world attack collection
---
## Notes
- `forwarder.py` must run continuously while Cowrie is active.
- All LLM inference is performed **locally**; no external API keys are required.
- If Docker reports container conflicts, remove old containers:
  ```bash
  docker rm -f cowrie
