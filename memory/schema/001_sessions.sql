-- One row per user conversation.
CREATE TABLE IF NOT EXISTS sessions (
    session_id  TEXT PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_run_id TEXT,
    last_criteria_fingerprint TEXT
);
