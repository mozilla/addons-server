ALTER TABLE `files` ADD COLUMN `is_packaged` bool NOT NULL DEFAULT 0;
CREATE INDEX `files_is_packaged` ON `files` (`is_packaged`);
