-- Agent execution timeline, persisted for replay after page reload.
CREATE TABLE IF NOT EXISTS trace_events (
    event_id SERIAL PRIMARY KEY,
    run_id   TEXT NOT NULL REFERENCES runs(run_id),
    ts       TIMESTAMPTZ NOT NULL DEFAULT now(),
    agent    TEXT NOT NULL,
    kind     TEXT NOT NULL,
    summary  TEXT NOT NULL,
    data     JSONB
);

CREATE INDEX IF NOT EXISTS idx_trace_events_run_id ON trace_events (run_id);
CREATE INDEX IF NOT EXISTS idx_trace_events_ts ON trace_events (ts);
