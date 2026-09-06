#!/bin/bash
# Enhanced LandScout startup script with better cleanup
# Starts all services in the correct order

set -e

echo "🏞️  Starting LandScout..."
echo ""

# Get the absolute path to the repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$REPO_ROOT"
# Repo root so `import agents` / `import api` work. Tool clients
# (landwatch, collin_cad, collin_flood, fema_flood) are installed packages.
export PYTHONPATH="${REPO_ROOT}:${PYTHONPATH}"

# Set SSL certificate paths for Python 3.13 httpx/openai
export SSL_CERT_FILE="${REPO_ROOT}/.venv/lib/python3.13/site-packages/certifi/cacert.pem"
export REQUESTS_CA_BUNDLE="${REPO_ROOT}/.venv/lib/python3.13/site-packages/certifi/cacert.pem"

# Create logs directory if it doesn't exist
mkdir -p "${REPO_ROOT}/logs"

# Function to check if port is in use
port_in_use() {
    lsof -ti:$1 > /dev/null 2>&1
}

# Function to kill process on port
kill_port() {
    local port=$1
    local name=$2
    if port_in_use $port; then
        local pid=$(lsof -ti:$port)
        echo "⚠️  Port :$port already in use by PID $pid ($name)"
        echo "   Stopping old process..."
        kill -TERM $pid 2>/dev/null || true
        sleep 2
        # Force kill if still running
        if port_in_use $port; then
            kill -KILL $(lsof -ti:$port) 2>/dev/null || true
            sleep 1
        fi
        echo "   ✅ Cleaned up"
    fi
}

# Check and clean up any running services
echo "🔍 Checking for existing services..."
kill_port 8000 "API"
kill_port 8001 "Supervisor"
kill_port 8002 "Scout"
kill_port 8003 "Enricher"
kill_port 8004 "Scorer"
kill_port 8010 "MCP"
echo ""

# Check if .venv exists
if [ ! -d ".venv" ]; then
    echo "❌ Virtual environment not found."
    echo "   Creating venv and installing dependencies..."
    uv venv
    uv pip install -e ".[agents,dev]"
    echo "✅ Dependencies installed"
fi

# Verify installation
if ! .venv/bin/python -c "import agents" 2>/dev/null; then
    echo "⚠️  Package not installed. Installing..."
    uv pip install -e ".[agents,dev]"
fi

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null; then
    echo "❌ docker-compose not found. Please install Docker."
    exit 1
fi

# Start datastores
echo "1️⃣  Starting Postgres and Redis..."
docker-compose up -d
sleep 5

# Run migrations
echo "2️⃣  Running database migrations..."
.venv/bin/python memory/migrate.py

# Start MCP server
echo "3️⃣  Starting MCP server on :8010..."
.venv/bin/python tools/mcp_server/server.py > "${REPO_ROOT}/logs/mcp.log" 2>&1 &
MCP_PID=$!
sleep 3

# Start agents
echo "4️⃣  Starting agents..."
echo "   - Scout on :8002"
.venv/bin/python agents/scout/scout.py > "${REPO_ROOT}/logs/scout.log" 2>&1 &
SCOUT_PID=$!
sleep 2

echo "   - Enricher on :8003"
.venv/bin/python agents/enricher/enricher.py > "${REPO_ROOT}/logs/enricher.log" 2>&1 &
ENRICHER_PID=$!
sleep 2

echo "   - Scorer on :8004"
.venv/bin/python agents/scorer/scorer.py > "${REPO_ROOT}/logs/scorer.log" 2>&1 &
SCORER_PID=$!
sleep 2

echo "   - Supervisor on :8001"
.venv/bin/python agents/supervisor/supervisor.py > "${REPO_ROOT}/logs/supervisor.log" 2>&1 &
SUPERVISOR_PID=$!
sleep 2

# Start API
echo "5️⃣  Starting API on :8000..."
.venv/bin/python api/main.py > "${REPO_ROOT}/logs/api.log" 2>&1 &
API_PID=$!
sleep 3

echo ""
echo "✅ LandScout is running!"
echo ""
echo "📊 Services:"
echo "   UI:         http://localhost:8000"
echo "   API:        http://localhost:8000/health"
echo "   MCP:        http://localhost:8010"
echo "   Supervisor: http://localhost:8001"
echo "   Scout:      http://localhost:8002"
echo "   Enricher:   http://localhost:8003"
echo "   Scorer:     http://localhost:8004"
echo ""
echo "📝 Logs:"
echo "   API:        logs/api.log"
echo "   Supervisor: logs/supervisor.log"
echo "   Scout:      logs/scout.log"
echo "   Enricher:   logs/enricher.log"
echo "   Scorer:     logs/scorer.log"
echo "   MCP:        logs/mcp.log"
echo ""
echo "💡 Tips:"
echo "   - tail -f logs/*.log to monitor all logs"
echo "   - ./scripts/stop.sh to cleanly stop all services"
echo "   - ./scripts/reload.sh <service> to reload a single service"
echo ""
echo "Press Ctrl+C to stop all services..."

# Store PIDs for cleanup
echo "$MCP_PID $SCOUT_PID $ENRICHER_PID $SCORER_PID $SUPERVISOR_PID $API_PID" > .landscout.pids

# Enhanced cleanup trap
cleanup() {
    echo ""
    echo "🛑 Stopping LandScout..."
    
    # Kill all child processes
    if [ -f .landscout.pids ]; then
        for pid in $(cat .landscout.pids); do
            kill -TERM $pid 2>/dev/null || true
        done
        
        # Wait for graceful shutdown
        sleep 2
        
        # Force kill any remaining
        for pid in $(cat .landscout.pids); do
            kill -KILL $pid 2>/dev/null || true
        done
        
        rm -f .landscout.pids
    fi
    
    # Also kill by port as backup
    for port in 8000 8001 8002 8003 8004 8010; do
        if port_in_use $port; then
            kill -TERM $(lsof -ti:$port) 2>/dev/null || true
        fi
    done
    
    docker-compose down 2>/dev/null || true
    echo "✅ Stopped"
    exit 0
}

trap cleanup INT TERM EXIT

# Keep script running
wait
