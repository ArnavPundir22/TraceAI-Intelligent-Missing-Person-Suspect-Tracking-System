#!/usr/bin/env python3
"""TraceAI backend startup helper."""
import argparse
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the TraceAI backend server")
    parser.add_argument("--host", default=os.getenv("TRACEAI_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("TRACEAI_PORT", "8000")))
    parser.add_argument(
        "--reload",
        action="store_true",
        default=os.getenv("TRACEAI_RELOAD", "false").lower() == "true",
        help="Enable uvicorn auto-reload",
    )
    return parser.parse_args()


def ensure_runtime_dirs() -> None:
    for directory in (
        "data/db",
        "data/uploads",
        "data/embeddings",
        "data/snapshots",
        "data/models",
        "data/logs",
    ):
        (BACKEND_DIR / directory).mkdir(parents=True, exist_ok=True)


def main() -> None:
    try:
        import uvicorn
    except ImportError:
        print("Missing dependencies. Run: pip install -r requirements.txt")
        raise SystemExit(1)

    args = parse_args()
    ensure_runtime_dirs()

    print("\n" + "=" * 64)
    print(" TraceAI — Forensic Surveillance Intelligence")
    print("=" * 64)
    print(f" Dashboard  →  http://localhost:{args.port}")
    print(f" API Docs   →  http://localhost:{args.port}/api/docs")
    print(f" WebSocket  →  ws://localhost:{args.port}/ws")
    print(f" Reload     →  {'enabled' if args.reload else 'disabled'}")
    print("=" * 64 + "\n")

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_dirs=[str(BACKEND_DIR / "app")] if args.reload else None,
        log_level="info",
    )


if __name__ == "__main__":
    main()
