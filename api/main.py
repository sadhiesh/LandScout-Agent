"""FastAPI application for LandScout.

Main entry point on port :8000. Provides /chat, /events, /debug, and /health.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from agents.common.config import API_PORT
from agents.common.middleware import add_standard_cors, add_health_check

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("LandScout API starting up...")
    yield
    logger.info("LandScout API shutting down...")


# Create FastAPI app
app = FastAPI(
    title="LandScout API",
    description="Multi-agent land investment research system",
    version="1.0.0",
    lifespan=lifespan,
)

# Add standard middleware and health check
add_standard_cors(app)
add_health_check(app, "landscout-api")


@app.middleware("http")
async def add_run_id(request: Request, call_next):
    """Inject run_id into every request for tracing."""
    # Get or generate run_id
    run_id = request.headers.get("X-Run-ID", str(uuid.uuid4()))
    
    # Add to request state
    request.state.run_id = run_id
    
    # Process request
    response = await call_next(request)
    
    # Add run_id to response headers
    response.headers["X-Run-ID"] = run_id
    
    return response

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler to prevent stack trace leakage."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc),
            "run_id": getattr(request.state, "run_id", None),
        },
    )


# Import and include routers
from api.chat import router as chat_router
from api.config_routes import router as config_router
from api.debug import router as debug_router
from api.events import router as events_router
from api.logs_stream import router as logs_router
from api.sessions import router as sessions_router

app.include_router(chat_router)
app.include_router(sessions_router)
app.include_router(config_router)
app.include_router(debug_router, prefix="/debug")
app.include_router(logs_router, prefix="/debug")
app.include_router(events_router)

# Mount static files for the UI (ui-next)
ui_dist_path = Path(__file__).parent.parent / "ui-next" / "dist"
if ui_dist_path.exists():
    app.mount("/static", StaticFiles(directory=str(ui_dist_path)), name="static")
    logger.info(f"Mounted UI from {ui_dist_path}")
else:
    logger.warning(f"UI dist directory not found at {ui_dist_path}")

# Redirect root to the React build
from fastapi.responses import RedirectResponse

@app.get("/")
async def root():
    """Redirect root to the UI."""
    if (ui_dist_path / "index.html").exists():
        return RedirectResponse(url="/static/index.html")
    else:
        return {"message": "LandScout API - Run 'npm run build' in ui-next/ to build the React app"}


def main():
    """Run the API server."""
    import uvicorn
    
    logger.info(f"Starting LandScout API on port {API_PORT}")
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=API_PORT,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()
