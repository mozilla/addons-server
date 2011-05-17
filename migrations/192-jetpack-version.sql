ALTER TABLE files
  ADD COLUMN `jetpack_version` varchar(10);

CREATE INDEX jetpack_version_idx ON files (jetpack_version);
