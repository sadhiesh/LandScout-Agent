-- Add run_id column and fix constraint name for enrichments table
-- The original 004_enrichments.sql created UNIQUE(parcel_id, source) without a name,
-- but store.py expects enrichments_parcel_source constraint.

-- Add run_id column
ALTER TABLE enrichments 
ADD COLUMN IF NOT EXISTS run_id TEXT REFERENCES runs(run_id);

-- Drop the old unnamed unique constraint
ALTER TABLE enrichments 
DROP CONSTRAINT IF EXISTS enrichments_parcel_id_source_key;

-- Create the named constraint that store.py expects
-- Changed from (parcel_id, source) to (run_id, parcel_id, source) to allow
-- the same parcel to have different enrichments across different runs
ALTER TABLE enrichments
ADD CONSTRAINT enrichments_parcel_source 
UNIQUE (run_id, parcel_id, source);

-- Create index on run_id for query performance
CREATE INDEX IF NOT EXISTS idx_enrichments_run_id ON enrichments (run_id);
