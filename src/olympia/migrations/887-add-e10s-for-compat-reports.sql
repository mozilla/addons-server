ALTER TABLE `compatibility_reports` ADD COLUMN `app_multiprocess_enabled` bool NOT NULL DEFAULT false, ADD COLUMN `multiprocess_compatible` bool DEFAULT NULL;
