-- Final rankings and rationales for parcels.
CREATE TABLE IF NOT EXISTS scores (
    score_id         SERIAL PRIMARY KEY,
    parcel_id        TEXT NOT NULL REFERENCES parcels(parcel_id),
    run_id           TEXT NOT NULL REFERENCES runs(run_id),
    total_score      REAL NOT NULL,
    dimension_scores JSONB NOT NULL,
    rationale        TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(parcel_id, run_id)
);

CREATE INDEX IF NOT EXISTS idx_scores_run_id ON scores (run_id);
