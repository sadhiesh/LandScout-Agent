"""Session and user management API endpoints.

Non-debug read/write routes for user identity, sessions, messages, and searches.
Kept separate from /debug/* to preserve the read-only rule.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from memory.store import PostgresStore

logger = logging.getLogger(__name__)

router = APIRouter()


# Request/response models


class IdentifyRequest(BaseModel):
    """Request to identify or create a user by name."""
    name: str


class IdentifyResponse(BaseModel):
    """Response with user identity."""
    user_id: str
    display_name: str
    returning: bool  # True if user already existed


class UserResponse(BaseModel):
    """User data."""
    user_id: str
    display_name: str
    created_at: str
    last_seen_at: str


class SessionSummary(BaseModel):
    """Session list item."""
    session_id: str
    title: Optional[str]
    created_at: str
    last_seen_at: str
    run_count: int


class CreateSessionRequest(BaseModel):
    """Request to create a new session."""
    user_id: str


class CreateSessionResponse(BaseModel):
    """Response with new session ID."""
    session_id: str


class MessageResponse(BaseModel):
    """Chat message."""
    message_id: int
    session_id: str
    run_id: Optional[str]
    role: str
    content: str
    payload: Optional[dict[str, Any]]
    created_at: str


class SearchResponse(BaseModel):
    """Stored search result."""
    run_id: str
    session_id: str
    criteria: dict[str, Any]
    search_url: str
    total_matching: int
    returned: int
    listings: list[dict[str, Any]]
    created_at: str


# Routes


@router.post("/users/identify", response_model=IdentifyResponse)
async def identify_user(req: IdentifyRequest) -> IdentifyResponse:
    """Resolve or create user by normalized name."""
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    
    # Normalize for lookup
    name_key = name.lower().strip()
    
    with PostgresStore() as pg:
        user = pg.get_user_by_name_key(name_key)
        
        if user:
            # Returning user
            return IdentifyResponse(
                user_id=user["user_id"],
                display_name=user["display_name"],
                returning=True,
            )
        else:
            # New user
            user_id = str(uuid.uuid4())
            display_name = name.title()
            pg.upsert_user(user_id, display_name, name_key)
            
            return IdentifyResponse(
                user_id=user_id,
                display_name=display_name,
                returning=False,
            )


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: str) -> UserResponse:
    """Fetch user by ID."""
    with PostgresStore() as pg:
        user = pg.get_user(user_id)
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        return UserResponse(
            user_id=user["user_id"],
            display_name=user["display_name"],
            created_at=user["created_at"].isoformat(),
            last_seen_at=user["last_seen_at"].isoformat(),
        )


@router.get("/users/{user_id}/sessions", response_model=list[SessionSummary])
async def list_user_sessions(user_id: str) -> list[SessionSummary]:
    """List all sessions for a user, newest first."""
    with PostgresStore() as pg:
        sessions = pg.list_sessions_for_user(user_id)
        
        return [
            SessionSummary(
                session_id=s["session_id"],
                title=s.get("title"),
                created_at=s["created_at"].isoformat(),
                last_seen_at=s["last_seen_at"].isoformat(),
                run_count=s.get("run_count", 0),
            )
            for s in sessions
        ]


@router.post("/sessions", response_model=CreateSessionResponse)
async def create_session(req: CreateSessionRequest) -> CreateSessionResponse:
    """Create a new session for a user."""
    session_id = str(uuid.uuid4())
    
    with PostgresStore() as pg:
        # Verify user exists
        user = pg.get_user(req.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        pg.create_session(session_id, user_id=req.user_id)
    
    return CreateSessionResponse(session_id=session_id)


@router.get("/sessions/{session_id}/messages", response_model=list[MessageResponse])
async def get_session_messages(session_id: str) -> list[MessageResponse]:
    """Get all messages for a session in order."""
    with PostgresStore() as pg:
        messages = pg.get_messages(session_id)
        
        return [
            MessageResponse(
                message_id=m["message_id"],
                session_id=m["session_id"],
                run_id=m.get("run_id"),
                role=m["role"],
                content=m["content"],
                payload=m.get("payload"),
                created_at=m["created_at"].isoformat(),
            )
            for m in messages
        ]


@router.get("/sessions/{session_id}/searches", response_model=list[SearchResponse])
async def get_session_searches(session_id: str) -> list[SearchResponse]:
    """Get all stored search results for a session."""
    with PostgresStore() as pg:
        # Get all runs for the session
        session = pg.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Query searches by session_id (need to add this to store.py)
        # For now, return empty list
        # TODO: Add get_searches_by_session to store.py
        return []
