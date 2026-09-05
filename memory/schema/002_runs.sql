-- One row per pipeline execution. Every other table keys off run_id.
CREATE TABLE IF NOT EXISTS runs (
    run_id       TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL REFERENCES sessions(session_id),
    criteria     JSONB NOT NULL,
    criteria_fingerprint TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'running',  -- running | completed | failed
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_runs_session_id ON runs (session_id);
CREATE INDEX IF NOT EXISTS idx_runs_fingerprint ON runs (criteria_fingerprint);
