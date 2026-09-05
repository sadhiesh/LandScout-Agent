-- Chat messages for persistent conversation history.
CREATE TABLE IF NOT EXISTS messages (
    message_id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    run_id     TEXT,  -- nullable: identity turns have no run
    role       TEXT NOT NULL,  -- 'user' or 'assistant'
    content    TEXT NOT NULL,
    payload    JSONB,  -- shortlist/summary for re-rendering on reload
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages (session_id, message_id);
