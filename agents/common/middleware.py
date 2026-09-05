"""Shared FastAPI middleware and utilities for all agents."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def add_standard_cors(app: FastAPI) -> None:
    """Add standard CORS middleware for local development.
    
    Allows all origins, credentials, methods, and headers for local development.
    In production, restrict allow_origins to specific domains.
    
    Args:
        app: FastAPI application instance
    """
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def add_health_check(app: FastAPI, service_name: str) -> None:
    """Add standard health check endpoint.
    
    Registers a GET /health endpoint that returns service status.
    
    Args:
        app: FastAPI application instance
        service_name: Name of the service (e.g., "supervisor", "api")
    """
    @app.get("/health")
    async def health():
        return {"status": "healthy", "service": service_name}
