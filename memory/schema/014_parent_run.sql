-- Add parent_run_id to link clarification rounds together
-- This maintains trace continuity across clarification exchanges

ALTER TABLE runs ADD COLUMN parent_run_id TEXT;

CREATE INDEX idx_runs_parent ON runs(parent_run_id);

COMMENT ON COLUMN runs.parent_run_id IS 'Links clarification follow-ups to original run for trace continuity';
