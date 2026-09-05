-- Candidates returned by Scout.
CREATE TABLE IF NOT EXISTS parcels (
    parcel_id   TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL REFERENCES runs(run_id),
    source      TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    location    JSONB NOT NULL,
    basic_info  JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_parcels_run_id ON parcels (run_id, created_at);
