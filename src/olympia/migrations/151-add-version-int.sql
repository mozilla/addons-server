ALTER TABLE versions ADD COLUMN version_int bigint;
CREATE INDEX version_int_idx ON versions (version_int);
