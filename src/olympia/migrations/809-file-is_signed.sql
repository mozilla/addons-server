ALTER TABLE files
    ADD COLUMN `is_signed` bool NOT NULL DEFAULT false;

-- We already automatically signed some files on production, so let's backfill those.
UPDATE files, versions SET files.is_signed = 1 WHERE versions.id = files.version_id and versions.version LIKE '%.1-signed';
