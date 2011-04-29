ALTER TABLE compatibility_reports ADD COLUMN `modified` datetime DEFAULT NULL;
CREATE INDEX created_idx ON compatibility_reports (created);
CREATE INDEX guid_created_idx ON compatibility_reports (guid, created);
CREATE INDEX guid_wp_idx ON compatibility_reports (guid, works_properly);
