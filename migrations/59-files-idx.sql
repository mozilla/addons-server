CREATE INDEX statuschanged_idx ON files (datestatuschanged, version_id);
CREATE INDEX created_idx ON files (created, version_id);
