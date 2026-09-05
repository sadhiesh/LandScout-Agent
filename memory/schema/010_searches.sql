-- LandWatch search results stored as structured JSON per run.
CREATE TABLE IF NOT EXISTS searches (
    run_id         TEXT PRIMARY KEY REFERENCES runs(run_id),
    session_id     TEXT NOT NULL REFERENCES sessions(session_id),
    criteria       JSONB NOT NULL,
    search_url     TEXT NOT NULL,
    total_matching INTEGER NOT NULL,
    returned       INTEGER NOT NULL,
    listings       JSONB NOT NULL,  -- full array with lat/lon/address
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_searches_session_id ON searches (session_id, created_at DESC);
