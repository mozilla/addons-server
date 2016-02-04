-- This might take a while.
-- It's allowing nulls because we don't have that information for old records.
ALTER TABLE stats_contributions ADD COLUMN modified datetime;
