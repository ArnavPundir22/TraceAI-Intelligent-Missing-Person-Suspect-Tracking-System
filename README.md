# TraceAI — Intelligent Missing Person & Suspect Tracking System

TraceAI is a real-time forensic surveillance intelligence platform for identifying, tracking, and reconstructing the movement timeline of persons across distributed CCTV and uploaded video sources.

## Features

- Real-time dashboard with camera, watchlist, alert, and analytics views
- Person registry with watchlist categories and face enrollment
- Image-based identity search against enrolled embeddings
- Camera management with live stream start/stop controls
- Timeline reconstruction and recent alert monitoring
- Batch video upload with background processing status tracking
- WebSocket-powered live frame and alert updates

## Project Structure

```text
backend/
  app/
    api/        FastAPI routers
    core/       WebSocket connection manager
    models/     SQLAlchemy models and Pydantic schemas
    services/   Detection, embedding, tracking, and stream processing
  run.py        Backend startup helper
  requirements.txt
frontend/
  index.html
  src/
    api.js      Browser API client
    app.js      Main dashboard application logic
    styles.css  UI styling
setup.sh        One-command setup helper
```

## Quick Start

### 1. Automated setup

From the repository root:

```bash
chmod +x setup.sh
./setup.sh
```

This creates a virtual environment, upgrades pip tooling, installs backend dependencies, and compiles the backend sources as a quick verification step.

### 2. Manual setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r backend/requirements.txt
```

### 3. Start the backend

```bash
source .venv/bin/activate
python backend/run.py
```

Optional development reload:

```bash
python backend/run.py --reload
```

## Access Points

- Dashboard: `http://localhost:8000`
- API docs: `http://localhost:8000/api/docs`
- Health check: `http://localhost:8000/api/health`
- WebSocket: `ws://localhost:8000/ws`

## Frontend Pages

- **Dashboard** — operational overview, alert feed, and live preview grid
- **Live Cameras** — stream controls, detections, and heatmap inspection
- **Persons** — registry management and face enrollment
- **Identity Search** — probe image search against enrolled persons
- **Movement Timeline** — per-person camera timeline reconstruction
- **Alerts** — recent alerts and acknowledgement workflow
- **Upload** — recorded video ingestion and job progress tracking
- **Analytics** — detection volume and camera/watchlist summaries

## Notes

- The backend serves the frontend directly, so only the FastAPI server needs to be started.
- If heavyweight AI dependencies are unavailable at runtime, the backend falls back to mock detection/embedding behavior for demos where implemented.
- Uploaded files, generated embeddings, snapshots, logs, and the SQLite database are stored under `backend/data/`.
