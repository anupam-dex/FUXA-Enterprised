#!/usr/bin/env bash
# ==============================================================================
# FUXA Enterprise Fleet Manager Launcher
# Runs the master orchestrator to manage all Storage & View servers via PM2.
# ==============================================================================

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

VENV_PYTHON="$SCRIPT_DIR/venv/bin/python3"

# Setup lightweight virtual environment if not present
if [ ! -f "$VENV_PYTHON" ]; then
    echo "Creating Python virtual environment for Fleet Manager..."
    python3 -m venv "$SCRIPT_DIR/venv"
    "$SCRIPT_DIR/venv/bin/pip" install --upgrade pip fastapi uvicorn pydantic psutil requests
fi

echo "=========================================================================="
echo " 🚀 Launching FUXA Enterprise Fleet Manager on Port 9000..."
echo " 🌐 Dashboard: http://localhost:9000"
echo "=========================================================================="

cd "$SCRIPT_DIR/manager"
exec "$VENV_PYTHON" -m uvicorn server:app --host 0.0.0.0 --port 9000
