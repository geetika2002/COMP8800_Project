# AI-Driven Honeypot Data Collector

## Project Overview
This project is an AI-powered honeypot data collection and analysis system designed to capture, interpret, and visualize SSH attacker behavior.

It integrates:

- **Cowrie (SSH honeypot)** for attacker interaction  
- **FastAPI backend** for event ingestion  
- **LLM-based analysis** for interpreting attacker intent  
- **Forwarder script** for log parsing  
- **SQLite** for persistent storage  
- **React Dashboard** for visual analytics  

---

## System Workflow
```bash
(Attacker)
      │
      ▼
[Cowrie Honeypot]
      │  (LLM #1: Fake Shell Output)
      └──> FastAPI /api/respond → GPT-4o-mini → Cowrie
      │
      ▼
[Cowrie Container Logs]
      ▼
[forwarder.py]
      ▼
[FastAPI Collector /api/events]
      │  (LLM #2: Attacker-Intent Analysis)
      └──> GPT-4o-mini → stored in DB
      ▼
[SQLite Database]
      ▼
[React Dashboard]
(shows commands + LLM analysis)

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
- **OpenAI gpt-4o-mini**
  - Generates fake shell output for Cowrie
  - Produces attacker-intent analysis for the dashboard

### Frontend
- React (Vite)
- Recharts
- Node.js 20+

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
## Running the Prototype 
### 1. Start the FastAPI server
```bash
uvicorn server:app --reload
```
The server will be accessible at http://127.0.0.1:8000.

The FastAPI handles:
* /api/events → event ingestion + LLM analysis
* /api/respond → AI-generated fake shell output

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
* source IP
* command
* LLM analysis

### 5. Testing the Honeypot
```bash
ssh -p 2222 root@localhost
```
Try commands such as: 
* whoami
* ls
* pwd
* cat /etc/passwd

FastAPI should show:
* POST /api/respond → LLM shell response
* POST /api/events → event + LLM analysis stored

### 6. Start the React Dashboard
Source code is in: dashboard/
```bash
cd dashboard
npm install 
npm run dev 
```
Open the provided localhost URL to view:

* total attacks
* unique IPs
* attack trends
* command frequency
* IP distribution
* recent events with LLM analysis column

## LLM Features 

### AI-powered fake shell responses 
Cowrie intercepts commands → FastAPI → GPT-4o-mini → realistic but safe Linux output.

## Attacker-intent analysis stored in DB
When forwarder.py posts events:
* FastAPI sends command to LLM
* LLM generates a detailed attacker-intent summary
* Summary is saved to SQLite
* Dashboard displays the analysis

## Future Work 
1. Security and Isolation (Milestone 3)
   Harden containers, sandbox LLM calls, rate-limit attackers.
2. Local Model Integration (Ollama)
   Repalce OpenAI API with a free local LLM for offline use.
3. Dashboard Enhancements:
   * severity scoring
   * filtering/search
   * expandable LLM analysis cards
   * real-time event stream
4. Docker Compose Deployment
   Multi-container setup for Cowrie + FastAPI + Dashboard
   
## Notes
* The forwarder.py script must run continuously while Cowrie is active.
* If Docker shows conflicts, remove old containers:
  ```bash
  docker rm -f cowrie
  ```
* An OpenAI API key is required to start the LLM integration for milestone 2. Store your OPENAI_API_KEY in a .env file. 


