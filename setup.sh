#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${TRACEAI_VENV_DIR:-$ROOT_DIR/.venv}"

echo "==> Creating virtual environment at $VENV_DIR"
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

echo "==> Upgrading pip tooling"
python -m pip install --upgrade pip setuptools wheel

echo "==> Installing backend dependencies"
python -m pip install -r "$ROOT_DIR/backend/requirements.txt"

echo "==> Verifying backend imports"
python -m compileall "$ROOT_DIR/backend"

cat <<SUMMARY

Setup complete.
Activate the environment with:
  source "$VENV_DIR/bin/activate"

Start the backend with:
  python "$ROOT_DIR/backend/run.py"
SUMMARY
