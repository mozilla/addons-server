-- Note: that first line is not necessary on dev/stage/prod, which already have a default.
-- Uncomment it in your local environement if you have an old database that you don't want
-- to reset.
-- ALTER TABLE `versions` MODIFY COLUMN `has_info_request` tinyint(1) unsigned DEFAULT NULL
ALTER TABLE `addons_addonreviewerflags` ADD COLUMN `pending_info_request` datetime(6), ADD COLUMN `notified_about_expiring_info_request` bool NOT NULL DEFAULT false;
