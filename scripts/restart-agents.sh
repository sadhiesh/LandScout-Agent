#!/bin/bash
# Restart all agent services to pick up code changes

echo "Restarting LandScout agents..."

# Kill existing agent processes
pkill -f "agents/supervisor/supervisor.py" || true
pkill -f "agents/scout/scout.py" || true
pkill -f "agents/enricher/enricher.py" || true
pkill -f "agents/scorer/scorer.py" || true

sleep 2

# Start agents in background
echo "Starting Supervisor on port 8001..."
python agents/supervisor/supervisor.py > logs/supervisor.log 2>&1 &

echo "Starting Scout on port 8002..."
python agents/scout/scout.py > logs/scout.log 2>&1 &

echo "Starting Enricher on port 8003..."
python agents/enricher/enricher.py > logs/enricher.log 2>&1 &

echo "Starting Scorer on port 8004..."
python agents/scorer/scorer.py > logs/scorer.log 2>&1 &

sleep 2
echo "Agents restarted. Check logs/ for output."
