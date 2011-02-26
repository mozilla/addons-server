ALTER TABLE addons ADD COLUMN backup_version integer;
ALTER TABLE addons ADD CONSTRAINT backup_version_refs_id_718a6c31
    FOREIGN KEY (backup_version) REFERENCES versions (id);
