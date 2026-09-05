-- Add presentation fields to scores table
-- These enable cached shortlists to show highlights/drawbacks/considerations
-- without re-scoring.

ALTER TABLE scores
ADD COLUMN highlights JSONB NOT NULL DEFAULT '[]'::jsonb,
ADD COLUMN drawbacks JSONB NOT NULL DEFAULT '[]'::jsonb,
ADD COLUMN not_assessed JSONB NOT NULL DEFAULT '[]'::jsonb,
ADD COLUMN considerations JSONB NOT NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN scores.highlights IS 'Deterministic highlights derived from dimension scores >= threshold';
COMMENT ON COLUMN scores.drawbacks IS 'Deterministic drawbacks derived from dimension scores <= threshold';
COMMENT ON COLUMN scores.not_assessed IS 'Skipped dimensions with reasons';
COMMENT ON COLUMN scores.considerations IS 'LLM-generated external checks, clearly labeled as model judgement';
