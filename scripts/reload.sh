#!/bin/bash
# Quick reload script for individual services
# Usage: ./reload.sh [service_name]
#   service_name: supervisor, scout, enricher, scorer, api, mcp

SERVICE="${1:-supervisor}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Same contract as run.sh: repo root on PYTHONPATH; tool clients are installed.
export PYTHONPATH="${REPO_ROOT}:${PYTHONPATH}"
export SSL_CERT_FILE="${REPO_ROOT}/.venv/lib/python3.13/site-packages/certifi/cacert.pem"
export REQUESTS_CA_BUNDLE="${REPO_ROOT}/.venv/lib/python3.13/site-packages/certifi/cacert.pem"

# Read current PIDs
if [ ! -f ".landscout.pids" ]; then
    echo "❌ No running services found (.landscout.pids missing)"
    echo "   Start services with ./run.sh first"
    exit 1
fi

PIDS=($(cat .landscout.pids))
MCP_PID=${PIDS[0]}
SCOUT_PID=${PIDS[1]}
ENRICHER_PID=${PIDS[2]}
SCORER_PID=${PIDS[3]}
SUPERVISOR_PID=${PIDS[4]}
API_PID=${PIDS[5]}

reload_service() {
    local name=$1
    local pid_var=$2
    local port=$3
    local script=$4
    local log=$5
    
    local pid=${!pid_var}
    
    # Progress goes to stderr; stdout carries only the PID, because the caller
    # reads this function through command substitution.
    echo "🔄 Reloading $name (PID: $pid)..." >&2
    kill $pid 2>/dev/null || echo "   (already stopped)" >&2
    sleep 1
    
    echo "   Starting $name on :$port..." >&2
    .venv/bin/python $script > $log 2>&1 &
    local new_pid=$!
    echo "   ✅ $name restarted (new PID: $new_pid)" >&2
    
    echo $new_pid
}

case "$SERVICE" in
    supervisor)
        NEW_PID=$(reload_service "Supervisor" "SUPERVISOR_PID" 8001 "agents/supervisor/supervisor.py" "logs/supervisor.log")
        PIDS[4]=$NEW_PID
        ;;
    scout)
        NEW_PID=$(reload_service "Scout" "SCOUT_PID" 8002 "agents/scout/scout.py" "logs/scout.log")
        PIDS[1]=$NEW_PID
        ;;
    enricher)
        NEW_PID=$(reload_service "Enricher" "ENRICHER_PID" 8003 "agents/enricher/enricher.py" "logs/enricher.log")
        PIDS[2]=$NEW_PID
        ;;
    scorer)
        NEW_PID=$(reload_service "Scorer" "SCORER_PID" 8004 "agents/scorer/scorer.py" "logs/scorer.log")
        PIDS[3]=$NEW_PID
        ;;
    api)
        NEW_PID=$(reload_service "API" "API_PID" 8000 "api/main.py" "logs/api.log")
        PIDS[5]=$NEW_PID
        ;;
    mcp)
        NEW_PID=$(reload_service "MCP" "MCP_PID" 8010 "tools/mcp_server/server.py" "logs/mcp.log")
        PIDS[0]=$NEW_PID
        ;;
    *)
        echo "❌ Unknown service: $SERVICE"
        echo "   Valid services: supervisor, scout, enricher, scorer, api, mcp"
        exit 1
        ;;
esac

# Update PIDs file
echo "${PIDS[@]}" > .landscout.pids
echo ""
echo "✅ Done! Check logs/$(echo $SERVICE).log for output"
