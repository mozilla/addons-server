ALTER TABLE files ADD COLUMN uses_flash bool NOT NULL;
CREATE INDEX uses_flash_idx ON files (uses_flash);
