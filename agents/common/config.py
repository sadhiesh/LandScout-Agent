"""Shared configuration loaded from environment variables."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from repo root if present
_repo_root = Path(__file__).parent.parent.parent
_env_file = _repo_root / ".env"
if _env_file.exists():
    load_dotenv(_env_file)

# LLM configuration
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-5")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "eng_ai")
LLM_KEY_HELPER = os.getenv(
    "LLM_KEY_HELPER",
    "/Applications/devbar.app/Contents/MacOS/devbar auth claude",
)

# OpenRouter configuration
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

# Service ports
API_PORT = int(os.getenv("API_PORT", "8000"))
SUPERVISOR_PORT = int(os.getenv("SUPERVISOR_PORT", "8001"))
SCOUT_PORT = int(os.getenv("SCOUT_PORT", "8002"))
ENRICHER_PORT = int(os.getenv("ENRICHER_PORT", "8003"))
SCORER_PORT = int(os.getenv("SCORER_PORT", "8004"))
MCP_PORT = int(os.getenv("MCP_PORT", "8010"))

# Datastores
POSTGRES_DSN = os.getenv(
    "POSTGRES_DSN", "postgresql://landscout:landscout@localhost:5432/landscout"
)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
AUDIT_LOG_DIR = Path(os.getenv("AUDIT_LOG_DIR", "logs/audit"))

# Timeout configuration (seconds)
# Agent-to-agent timeouts
A2A_SUPERVISOR_TIMEOUT = int(os.getenv("A2A_SUPERVISOR_TIMEOUT", "1200"))  # 20 min
A2A_SCOUT_TIMEOUT = int(os.getenv("A2A_SCOUT_TIMEOUT", "300"))  # 5 min (search is fast)
A2A_ENRICHER_TIMEOUT = int(os.getenv("A2A_ENRICHER_TIMEOUT", "900"))  # 15 min (external APIs can be slow)
A2A_SCORER_TIMEOUT = int(os.getenv("A2A_SCORER_TIMEOUT", "900"))  # 15 min (includes LLM calls)

# LLM call timeout
LLM_CALL_TIMEOUT = int(os.getenv("LLM_CALL_TIMEOUT", "120"))  # 2 min

# HTTP client timeouts
HTTP_CLIENT_TIMEOUT = float(os.getenv("HTTP_CLIENT_TIMEOUT", "30.0"))  # 30 sec
SSE_HEARTBEAT_INTERVAL = float(os.getenv("SSE_HEARTBEAT_INTERVAL", "15.0"))  # 15 sec

# Development flags
DISABLE_CRITERIA_CACHE = os.getenv("DISABLE_CRITERIA_CACHE", "false").lower() == "true"
