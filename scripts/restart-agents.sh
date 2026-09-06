#!/bin/bash
# Restart all agent services to pick up code changes

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$REPO_ROOT"

# Same certificate setup as the main startup scripts.
export SSL_CERT_FILE="${REPO_ROOT}/.venv/lib/python3.13/site-packages/certifi/cacert.pem"
export REQUESTS_CA_BUNDLE="${REPO_ROOT}/.venv/lib/python3.13/site-packages/certifi/cacert.pem"

echo "Restarting LandScout agents..."

# Kill existing agent processes
pkill -f "agents/supervisor/supervisor.py" || true
pkill -f "agents/scout/scout.py" || true
pkill -f "agents/enricher/enricher.py" || true
pkill -f "agents/scorer/scorer.py" || true

sleep 2

# Start agents in background
echo "Starting Supervisor on port 8001..."
.venv/bin/python agents/supervisor/supervisor.py > logs/supervisor.log 2>&1 &

echo "Starting Scout on port 8002..."
.venv/bin/python agents/scout/scout.py > logs/scout.log 2>&1 &

echo "Starting Enricher on port 8003..."
.venv/bin/python agents/enricher/enricher.py > logs/enricher.log 2>&1 &

echo "Starting Scorer on port 8004..."
.venv/bin/python agents/scorer/scorer.py > logs/scorer.log 2>&1 &

sleep 2
echo "Agents restarted. Check logs/ for output."
