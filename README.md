# Honeypot Data Collector 

## Project Overview 
This project is a honeypot data collection system designed to capture and analyze SSH attacker activity. It uses **Cowrie** as the honeypot, a **FastAPI server** to receive and store events, a **forwarder script** to parse and send logs, and a **SQLite database** to persist the collected data. The backend data is visualized through an analytical React Dashboard. 

Current prototype workflow: 
(Attacker)
-->
[Cowrie Honeypot]
-->
[Forwarder.py]
-->
[FastAPI Server / Collector]
-->
[SQLite Database]
-->
[React Dashboard]

---

## Tech Stack
- **Cowrie**: SSH honeypot (Dockerized)  
- **Python 3.12**: Backend scripting  
- **FastAPI**: REST API server  
- **SQLite**: Event storage  
- **Requests**: HTTP client for forwarding logs  
- **Docker**: Containerized deployment
- **React**: Frontend for dashboard element

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
pip install -r requirements.txt
# or manually:
pip install fastapi[all] requests sqlite3 pydantic uvicorn
```
## Running the Prototype 
### 1. Start the FastAPI server
```bash
uvicorn server:app --reload
```
The server will be accessible at http://127.0.0.1:8000.

### 2. Start Cowrie honeypot in Docker 
```bash
docker run -d --name cowrie -p 2222:2222 cowrie/cowrie:latest
```
Port 2222 will simulate an SSH service.

To view logs: 
```bash
docker logs -f cowrie
```
### 3. Run the forwarder script
The forwarder reads Cowrie logs, parses them, and sends JSON events to the server.
```bash
python forwarder.py
```
### 4. Verify database storage 
```bash
sqlite3 events.db
sqlite> select * from events;
```
You should see logged attacker activity (timestamp, command, source IP, etc.).

### 5. Testing the backend setup
```bash
ssh -p 2222 root@localhost
```
* Run any command (e.g., ls -al /tmp).
* Observe the POST /api/events requests in the server terminal.
* Check events.db to confirm the event is stored.

### 6. Start the frontend 
The frontend is a React framework and all source code is located in the "dashboard" folder; look at app.jsx specifically for the code structure. Ensure that you have react and Node.js version 20 or above installed. I also have installed recharts which is an npm dependancy. 

Run the following commands to get the dashboard up and running. 
```bash
cd dashboard
npm install 
npm run dev 
```
This will output a link to a localhost:[port]. Access the link via your browser to see the dashboard. It will be linked to the backend, and all analytics will show up accordingly. 

## Future Work 
1. Update dashboard with further features, however main functionality is present. 
2. Add LLM module to respond to attackers through the honeypot.
3. Enhance log parsing and event metadata collection.
4. Deploy multi-container setup with Docker Compose.

## Notes
* The forwarder.py script must run continuously while Cowrie is active.
* If using Docker, avoid multiple containers with the same name; remove old containers first:
  ```bash
  docker rm -f cowrie
```


