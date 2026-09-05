-- Per-parcel enrichment data from external sources.
CREATE TABLE IF NOT EXISTS enrichments (
    enrichment_id SERIAL PRIMARY KEY,
    parcel_id     TEXT NOT NULL REFERENCES parcels(parcel_id),
    source        TEXT NOT NULL,
    data          JSONB NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(parcel_id, source)
);

CREATE INDEX IF NOT EXISTS idx_enrichments_parcel_id ON enrichments (parcel_id);
