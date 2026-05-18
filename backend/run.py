#!/usr/bin/env python3
"""TraceAI — Backend Startup Script. Run: python run.py"""
import sys
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

try:
    import uvicorn
except ImportError:
    print("Missing dependencies. Run: pip install -r requirements.txt")
    sys.exit(1)

def main():
    print("\n" + "="*60)
    print("  TraceAI — Forensic Surveillance Intelligence v1.0.0")
    print("="*60)
    print("  Dashboard  →  http://localhost:8000")
    print("  API Docs   →  http://localhost:8000/api/docs")
    print("  WebSocket  →  ws://localhost:8000/ws")
    print("="*60 + "\n")

    for d in ["data/db","data/uploads","data/embeddings","data/snapshots","data/models","data/logs"]:
        Path(d).mkdir(parents=True, exist_ok=True)

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=[str(BACKEND_DIR / "app")],
        log_level="info",
    )

if __name__ == "__main__":
    main()
