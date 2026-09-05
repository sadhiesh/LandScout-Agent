-- Fix parcels primary key to be composite (run_id, parcel_id) to allow
-- the same property_id across multiple runs without collision.

-- Drop existing constraints and indexes
ALTER TABLE enrichments DROP CONSTRAINT IF EXISTS enrichments_parcel_id_fkey;
ALTER TABLE scores DROP CONSTRAINT IF EXISTS scores_parcel_id_fkey;
ALTER TABLE parcels DROP CONSTRAINT IF EXISTS parcels_pkey;
DROP INDEX IF EXISTS idx_parcels_run_id;

-- Change parcels to composite PK
ALTER TABLE parcels ADD PRIMARY KEY (run_id, parcel_id);

-- Update enrichments to reference composite key
ALTER TABLE enrichments DROP COLUMN IF EXISTS parcel_id;
ALTER TABLE enrichments ADD COLUMN run_id TEXT NOT NULL DEFAULT '';
ALTER TABLE enrichments ADD COLUMN parcel_id TEXT NOT NULL DEFAULT '';
ALTER TABLE enrichments DROP CONSTRAINT IF EXISTS enrichments_pkey;
ALTER TABLE enrichments DROP CONSTRAINT IF EXISTS enrichments_parcel_id_source_key;
ALTER TABLE enrichments ADD PRIMARY KEY (enrichment_id);
ALTER TABLE enrichments ADD CONSTRAINT enrichments_parcel_fkey 
    FOREIGN KEY (run_id, parcel_id) REFERENCES parcels(run_id, parcel_id);
CREATE UNIQUE INDEX idx_enrichments_parcel_source ON enrichments (run_id, parcel_id, source);

-- Update scores to reference composite key  
ALTER TABLE scores DROP CONSTRAINT IF EXISTS scores_parcel_id_run_id_key;
ALTER TABLE scores ADD CONSTRAINT scores_parcel_fkey 
    FOREIGN KEY (run_id, parcel_id) REFERENCES parcels(run_id, parcel_id);
CREATE UNIQUE INDEX idx_scores_parcel_run ON scores (run_id, parcel_id);
