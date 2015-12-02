ALTER TABLE `files` ADD COLUMN `binary` bool NOT NULL DEFAULT '0';
-- Update files.binary with current value of addons.binary.
UPDATE files, versions, addons SET files.binary=1 WHERE files.version_id=versions.id AND versions.addon_id=addons.id AND addons.binary=1;
-- Not dropping addons.binary in case remora is still using it.
