"""Pydantic schemas for LandScout memory and API contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# Core entities

class Session(BaseModel):
    """User conversation session."""
    
    session_id: str
    created_at: datetime
    last_run_id: Optional[str] = None
    last_criteria_fingerprint: Optional[str] = None


class SearchCriteria(BaseModel):
    """Land search criteria extracted from user input."""
    
    state: str = Field(description="US state code (e.g., TX, NV)")
    county: Optional[str] = Field(default=None, description="County name")
    acres_min: Optional[float] = Field(default=None, ge=0)
    acres_max: Optional[float] = Field(default=None, ge=0)
    price_min: Optional[float] = Field(default=None, ge=0)
    price_max: Optional[float] = Field(default=None, ge=0)
    property_types: list[str] = Field(
        default_factory=list,
        description="e.g., land, ranch, farm, recreational",
    )
    features: list[str] = Field(
        default_factory=list,
        description="e.g., water, utilities, road_access",
    )


class Run(BaseModel):
    """Pipeline execution run."""
    
    run_id: str
    session_id: str
    created_at: datetime
    criteria: SearchCriteria
    criteria_fingerprint: str
    status: Literal["running", "completed", "failed"] = "running"
    completed_at: Optional[datetime] = None


class Location(BaseModel):
    """Parcel location data."""
    
    state: str
    county: str
    city: Optional[str] = None
    zip_code: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None


class BasicInfo(BaseModel):
    """Core parcel attributes from search."""
    
    title: str
    acres: float
    price: float
    price_per_acre: float
    url: str
    thumbnail_url: Optional[str] = None


class Parcel(BaseModel):
    """Land parcel entity."""
    
    parcel_id: str
    run_id: str
    source: str
    source_id: str
    location: Location
    basic_info: BasicInfo
    created_at: datetime


class Enrichment(BaseModel):
    """Enrichment data from external source."""
    
    enrichment_id: int
    parcel_id: str
    source: str
    data: dict[str, Any]
    created_at: datetime


class DimensionScore(BaseModel):
    """Score breakdown for one dimension."""
    
    dimension: str
    weight: float
    raw_score: float
    weighted_score: float


class Score(BaseModel):
    """Final parcel score and rationale."""
    
    score_id: int
    parcel_id: str
    run_id: str
    total_score: float
    dimension_scores: dict[str, DimensionScore]
    rationale: str
    created_at: datetime


# Trace events

class TraceEvent(BaseModel):
    """Agent execution trace event."""
    
    event_id: Optional[int] = None
    run_id: str
    ts: datetime = Field(default_factory=datetime.utcnow)
    agent: str = Field(description="supervisor, scout, enricher, scorer")
    kind: Literal[
        "thought",
        "route",
        "a2a_send",
        "a2a_recv",
        "tool_call",
        "tool_result",
        "error",
        "subagent_start",
        "subagent_finish",
        "memory_read",
        "memory_write",
        "context",
        "llm_call",
        "llm_response",
        "pipeline_timing",  # Performance monitoring: overall pipeline breakdown
    ]
    summary: str = Field(description="Short human-readable description")
    data: Optional[dict[str, Any]] = Field(
        default=None, description="Structured detail for debug inspection"
    )


# API contracts

class ChatRequest(BaseModel):
    """User message to the system."""
    
    session_id: str
    message: str


class ChatResponse(BaseModel):
    """System response to user."""
    
    run_id: str
    message: str
    parcels: list[Parcel] = Field(default_factory=list)
    scores: list[Score] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    """Error response."""
    
    error: str
    detail: Optional[str] = None
