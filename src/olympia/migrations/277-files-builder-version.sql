ALTER TABLE files ADD COLUMN `builder_version` varchar(10) NULL;
CREATE INDEX builder_version_idx ON files (builder_version);
