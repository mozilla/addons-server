ALTER TABLE `addons` ADD COLUMN `is_packaged` bool NOT NULL DEFAULT 0;
CREATE INDEX `addons_is_packaged` ON `addons` (`is_packaged`);
-- Move existing flags from files to addons.
UPDATE files, versions, addons SET addons.is_packaged=1 WHERE files.version_id=versions.id AND versions.addon_id=addons.id AND files.is_packaged=1;
-- Drop files column.
ALTER TABLE `files` DROP COLUMN `is_packaged`;
