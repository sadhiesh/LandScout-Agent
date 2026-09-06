#!/bin/bash
# LandScout shutdown script
# Stops all services started by run.sh

set +e  # Don't exit on errors during cleanup

echo "🛑 Stopping LandScout..."
echo ""

# Get the absolute path to the repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$REPO_ROOT"

PID_FILE=".landscout.pids"

# Function to gracefully stop a process
stop_process() {
    local pid=$1
    local name=$2
    
    if [ -z "$pid" ]; then
        return
    fi
    
    # Check if process exists
    if ! ps -p "$pid" > /dev/null 2>&1; then
        return
    fi
    
    echo "   Stopping $name (PID: $pid)..."
    
    # Try graceful shutdown first (SIGTERM)
    kill -TERM "$pid" 2>/dev/null || true
    
    # Wait up to 5 seconds for graceful shutdown
    for i in {1..10}; do
        if ! ps -p "$pid" > /dev/null 2>&1; then
            return
        fi
        sleep 0.5
    done
    
    # Force kill if still running
    if ps -p "$pid" > /dev/null 2>&1; then
        echo "   Force stopping $name..."
        kill -KILL "$pid" 2>/dev/null || true
        sleep 0.5
    fi
}

# Stop Python services by PID file first
if [ -f "$PID_FILE" ]; then
    echo "1️⃣  Stopping Python services from PID file..."
    
    # Read PIDs from file
    read -r MCP_PID SCOUT_PID ENRICHER_PID SCORER_PID SUPERVISOR_PID API_PID < "$PID_FILE"
    
    # Stop in reverse order of startup
    stop_process "$API_PID" "API"
    stop_process "$SUPERVISOR_PID" "Supervisor"
    stop_process "$SCORER_PID" "Scorer"
    stop_process "$ENRICHER_PID" "Enricher"
    stop_process "$SCOUT_PID" "Scout"
    stop_process "$MCP_PID" "MCP server"
    
    # Clean up PID file
    rm -f "$PID_FILE"
fi

# Always check ports as backup (in case PIDs were stale or file missing)
# case lookup (not declare -A) — macOS /bin/bash is 3.2 and has no associative arrays
echo "1️⃣  Cleaning up any remaining processes by port..."
port_name() {
    case "$1" in
        8000) echo "API" ;;
        8001) echo "Supervisor" ;;
        8002) echo "Scout" ;;
        8003) echo "Enricher" ;;
        8004) echo "Scorer" ;;
        8010) echo "MCP" ;;
        *)    echo "port-$1" ;;
    esac
}

for port in 8000 8001 8002 8003 8004 8010; do
    pid=$(lsof -ti:$port 2>/dev/null)
    if [ -n "$pid" ]; then
        name=$(port_name "$port")
        echo "   Stopping $name on port :$port (PID: $pid)..."
        stop_process "$pid" "$name"
    fi
done

# Stop Docker services
echo "2️⃣  Stopping Postgres and Redis..."
if command -v docker-compose &> /dev/null; then
    docker-compose down 2>/dev/null || echo "   (docker-compose not running or already stopped)"
else
    echo "   (docker-compose not available)"
fi

echo ""
echo "✅ LandScout stopped"
echo ""
