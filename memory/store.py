"""Datastore interfaces for Postgres and Redis.

This module provides thin wrappers around psycopg and redis-py for the
LandScout memory layer. All SQL lives here, not scattered through agents.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

import psycopg
import redis
from psycopg.rows import dict_row

from agents.common.config import POSTGRES_DSN, REDIS_URL

logger = logging.getLogger(__name__)


class PostgresStore:
    """Postgres interface for durable memory.
    
    Manages sessions, runs, parcels, enrichments, scores, and trace events.
    """
    
    def __init__(self, dsn: str = POSTGRES_DSN):
        self.dsn = dsn
        self._conn: Optional[psycopg.Connection] = None
    
    def connect(self) -> None:
        """Establish database connection."""
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(self.dsn, row_factory=dict_row)
            logger.info("Connected to Postgres")
    
    def close(self) -> None:
        """Close database connection."""
        if self._conn and not self._conn.closed:
            self._conn.close()
            logger.info("Closed Postgres connection")
    
    def __enter__(self) -> PostgresStore:
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
    
    # Users
    
    def upsert_user(
        self, user_id: str, display_name: str, name_key: str
    ) -> dict[str, Any]:
        """Create or update a user."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (user_id, display_name, name_key, last_seen_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (user_id) DO UPDATE 
                SET display_name = EXCLUDED.display_name,
                    last_seen_at = NOW()
                RETURNING *
                """,
                (user_id, display_name, name_key),
            )
            self._conn.commit()
            return cur.fetchone()
    
    def get_user(self, user_id: str) -> Optional[dict[str, Any]]:
        """Fetch user by ID."""
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM users WHERE user_id = %s",
                (user_id,),
            )
            return cur.fetchone()
    
    def get_user_by_name_key(self, name_key: str) -> Optional[dict[str, Any]]:
        """Fetch user by normalized name."""
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM users WHERE name_key = %s",
                (name_key,),
            )
            return cur.fetchone()
    
    # Sessions
    
    def create_session(
        self, session_id: str, user_id: Optional[str] = None, title: Optional[str] = None
    ) -> dict[str, Any]:
        """Create a new session."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sessions (session_id, user_id, title) 
                VALUES (%s, %s, %s) 
                RETURNING *
                """,
                (session_id, user_id, title),
            )
            self._conn.commit()
            return cur.fetchone()
    
    def get_session(self, session_id: str) -> Optional[dict[str, Any]]:
        """Fetch session by ID."""
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM sessions WHERE session_id = %s",
                (session_id,),
            )
            return cur.fetchone()
    
    def update_session_last_run(
        self, session_id: str, run_id: str, fingerprint: str
    ) -> None:
        """Update session's last run and criteria fingerprint."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE sessions 
                SET last_run_id = %s, last_criteria_fingerprint = %s
                WHERE session_id = %s
                """,
                (run_id, fingerprint, session_id),
            )
            self._conn.commit()
    
    def list_sessions_for_user(self, user_id: str) -> list[dict[str, Any]]:
        """List all sessions for a user, newest first."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT s.*, COUNT(r.run_id) as run_count
                FROM sessions s
                LEFT JOIN runs r ON s.session_id = r.session_id
                WHERE s.user_id = %s
                GROUP BY s.session_id
                ORDER BY s.last_seen_at DESC
                """,
                (user_id,),
            )
            return cur.fetchall()
    
    def touch_session(
        self, session_id: str, user_id: Optional[str] = None, title: Optional[str] = None
    ) -> None:
        """Update session's last_seen_at, optionally setting user_id and title."""
        with self._conn.cursor() as cur:
            updates = ["last_seen_at = NOW()"]
            params = []
            
            if user_id is not None:
                updates.append("user_id = %s")
                params.append(user_id)
            if title is not None:
                updates.append("title = %s")
                params.append(title)
            
            params.append(session_id)
            
            cur.execute(
                f"UPDATE sessions SET {', '.join(updates)} WHERE session_id = %s",
                tuple(params),
            )
            self._conn.commit()
    
    # Runs
    
    def create_run(
        self,
        run_id: str,
        session_id: str,
        criteria: dict[str, Any],
        fingerprint: str,
        parent_run_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a new run.
        
        Args:
            run_id: Unique run identifier
            session_id: Session this run belongs to
            criteria: Search criteria for this run
            fingerprint: SHA256 fingerprint of criteria
            parent_run_id: Optional parent run ID for clarification continuity
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO runs (run_id, session_id, criteria, criteria_fingerprint, parent_run_id)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
                """,
                (run_id, session_id, json.dumps(criteria), fingerprint, parent_run_id),
            )
            self._conn.commit()
            return cur.fetchone()
    
    def get_run(self, run_id: str) -> Optional[dict[str, Any]]:
        """Fetch run by ID."""
        with self._conn.cursor() as cur:
            cur.execute("SELECT * FROM runs WHERE run_id = %s", (run_id,))
            return cur.fetchone()
    
    def update_run_status(
        self, run_id: str, status: str, completed_at: Optional[datetime] = None
    ) -> None:
        """Update run status and optional completion timestamp."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE runs 
                SET status = %s, completed_at = %s
                WHERE run_id = %s
                """,
                (status, completed_at, run_id),
            )
            self._conn.commit()
    
    def get_runs_by_fingerprint(
        self, session_id: str, fingerprint: str
    ) -> list[dict[str, Any]]:
        """Find runs matching a criteria fingerprint in a session."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM runs
                WHERE session_id = %s AND criteria_fingerprint = %s
                ORDER BY created_at DESC
                """,
                (session_id, fingerprint),
            )
            return cur.fetchall()
    
    # Messages
    
    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        run_id: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Append a message to a session."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO messages (session_id, run_id, role, content, payload)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    session_id,
                    run_id,
                    role,
                    content,
                    json.dumps(payload) if payload else None,
                ),
            )
            self._conn.commit()
            return cur.fetchone()
    
    def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        """Get all messages for a session in order."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM messages
                WHERE session_id = %s
                ORDER BY message_id
                """,
                (session_id,),
            )
            return cur.fetchall()
    
    # Searches
    
    def insert_search(
        self,
        run_id: str,
        session_id: str,
        criteria: dict[str, Any],
        search_url: str,
        total_matching: int,
        returned: int,
        listings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Insert a search result."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO searches 
                (run_id, session_id, criteria, search_url, total_matching, returned, listings)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    run_id,
                    session_id,
                    json.dumps(criteria),
                    search_url,
                    total_matching,
                    returned,
                    json.dumps(listings),
                ),
            )
            self._conn.commit()
            return cur.fetchone()
    
    def get_search(self, run_id: str) -> Optional[dict[str, Any]]:
        """Get search result for a run."""
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM searches WHERE run_id = %s",
                (run_id,),
            )
            return cur.fetchone()
    
    # Parcels
    
    def insert_parcel(
        self,
        parcel_id: str,
        run_id: str,
        source: str,
        source_id: str,
        location: dict[str, Any],
        basic_info: dict[str, Any],
    ) -> dict[str, Any]:
        """Insert a new parcel (or update if exists)."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO parcels 
                (parcel_id, run_id, source, source_id, location, basic_info)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id, parcel_id) DO UPDATE
                SET source = EXCLUDED.source,
                    source_id = EXCLUDED.source_id,
                    location = EXCLUDED.location,
                    basic_info = EXCLUDED.basic_info
                RETURNING *
                """,
                (
                    parcel_id,
                    run_id,
                    source,
                    source_id,
                    json.dumps(location),
                    json.dumps(basic_info),
                ),
            )
            self._conn.commit()
            return cur.fetchone()
    
    def get_parcels_by_run(self, run_id: str) -> list[dict[str, Any]]:
        """Fetch all parcels for a run."""
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM parcels WHERE run_id = %s ORDER BY created_at",
                (run_id,),
            )
            return cur.fetchall()
    
    # Enrichments
    
    def insert_enrichment(
        self, run_id: str, parcel_id: str, source: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Insert enrichment data for a parcel."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO enrichments (run_id, parcel_id, source, data)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT ON CONSTRAINT enrichments_parcel_source
                DO UPDATE SET data = EXCLUDED.data
                RETURNING *
                """,
                (run_id, parcel_id, source, json.dumps(data)),
            )
            self._conn.commit()
            return cur.fetchone()
    
    def get_enrichments_by_parcel(
        self, run_id: str, parcel_id: str
    ) -> list[dict[str, Any]]:
        """Fetch all enrichments for a parcel in a run."""
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM enrichments WHERE run_id = %s AND parcel_id = %s",
                (run_id, parcel_id),
            )
            return cur.fetchall()
    
    # Scores
    
    def insert_score(
        self,
        parcel_id: str,
        run_id: str,
        total_score: float,
        dimension_scores: dict[str, float],
        rationale: str,
        highlights: list[dict[str, Any]] | None = None,
        drawbacks: list[dict[str, Any]] | None = None,
        not_assessed: list[dict[str, Any]] | None = None,
        considerations: list[str] | None = None,
    ) -> dict[str, Any]:
        """Insert score, rationale, and presentation fields for a parcel."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO scores 
                (parcel_id, run_id, total_score, dimension_scores, rationale,
                 highlights, drawbacks, not_assessed, considerations)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (parcel_id, run_id) DO UPDATE 
                SET total_score = EXCLUDED.total_score,
                    dimension_scores = EXCLUDED.dimension_scores,
                    rationale = EXCLUDED.rationale,
                    highlights = EXCLUDED.highlights,
                    drawbacks = EXCLUDED.drawbacks,
                    not_assessed = EXCLUDED.not_assessed,
                    considerations = EXCLUDED.considerations
                RETURNING *
                """,
                (
                    parcel_id,
                    run_id,
                    total_score,
                    json.dumps(dimension_scores),
                    rationale,
                    json.dumps(highlights or []),
                    json.dumps(drawbacks or []),
                    json.dumps(not_assessed or []),
                    json.dumps(considerations or []),
                ),
            )
            self._conn.commit()
            return cur.fetchone()
    
    def get_scores_by_run(self, run_id: str) -> list[dict[str, Any]]:
        """Fetch all scores for a run, ordered by score descending."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM scores 
                WHERE run_id = %s 
                ORDER BY total_score DESC
                """,
                (run_id,),
            )
            return cur.fetchall()
    
    # Trace events
    
    def insert_trace_event(
        self,
        run_id: str,
        agent: str,
        kind: str,
        summary: str,
        data: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Insert a trace event."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO trace_events (run_id, agent, kind, summary, data)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
                """,
                (run_id, agent, kind, summary, json.dumps(data) if data else None),
            )
            self._conn.commit()
            return cur.fetchone()
    
    def get_trace_events_by_run(self, run_id: str) -> list[dict[str, Any]]:
        """Fetch all trace events for a run, ordered by timestamp."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM trace_events 
                WHERE run_id = %s 
                ORDER BY ts
                """,
                (run_id,),
            )
            return cur.fetchall()


class RedisStore:
    """Redis interface for ephemeral memory and pub/sub.
    
    Manages session state and trace event streaming.
    """
    
    def __init__(self, url: str = REDIS_URL):
        self.url = url
        self._client: Optional[redis.Redis] = None
    
    def connect(self) -> None:
        """Establish Redis connection."""
        if self._client is None:
            self._client = redis.from_url(
                self.url, decode_responses=True
            )
            logger.info("Connected to Redis")
    
    def close(self) -> None:
        """Close Redis connection."""
        if self._client:
            self._client.close()
            logger.info("Closed Redis connection")
    
    def __enter__(self) -> RedisStore:
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
    
    # Session ephemeral state
    
    def set_session_state(
        self, session_id: str, key: str, value: Any, ttl: int = 3600
    ) -> None:
        """Set ephemeral session state with TTL."""
        full_key = f"session:{session_id}:{key}"
        self._client.setex(full_key, ttl, json.dumps(value))
    
    def get_session_state(
        self, session_id: str, key: str
    ) -> Optional[Any]:
        """Get ephemeral session state."""
        full_key = f"session:{session_id}:{key}"
        value = self._client.get(full_key)
        return json.loads(value) if value else None
    
    def delete_session_state(self, session_id: str, key: str) -> None:
        """Delete ephemeral session state."""
        full_key = f"session:{session_id}:{key}"
        self._client.delete(full_key)
    
    # Trace event pub/sub
    
    def publish_trace_event(self, run_id: str, event: dict[str, Any]) -> None:
        """Publish a trace event to the run's channel."""
        channel = f"trace:{run_id}"
        self._client.publish(channel, json.dumps(event))
    
    def subscribe_trace_events(self, run_id: str):
        """Subscribe to trace events for a run.
        
        Yields:
            dict: Trace events as they arrive
        """
        channel = f"trace:{run_id}"
        pubsub = self._client.pubsub()
        pubsub.subscribe(channel)
        
        try:
            for message in pubsub.listen():
                if message["type"] == "message":
                    yield json.loads(message["data"])
        finally:
            pubsub.unsubscribe(channel)
            pubsub.close()
