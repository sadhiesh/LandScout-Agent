-- Add user_id to sessions and session metadata columns.
ALTER TABLE sessions ADD COLUMN user_id TEXT REFERENCES users(user_id);
ALTER TABLE sessions ADD COLUMN title TEXT;
ALTER TABLE sessions ADD COLUMN last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions (user_id, last_seen_at DESC);
