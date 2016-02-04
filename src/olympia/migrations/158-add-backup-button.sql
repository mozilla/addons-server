ALTER TABLE addons ADD COLUMN backup_version int(11) unsigned;
ALTER TABLE addons ADD CONSTRAINT addons_ibfk_16 FOREIGN KEY (backup_version) REFERENCES versions (id) ON DELETE SET NULL;
