UPDATE `config` SET `key`="AUTO_APPROVAL_MAX_AUTO_APPROVED_UPDATES" WHERE `key`="AUTO_APPROVAL_MIN_APPROVED_UPDATES";
TRUNCATE TABLE `editors_autoapprovalsummary`;
ALTER TABLE `editors_autoapprovalsummary` DROP COLUMN `approved_updates`;
ALTER TABLE `editors_autoapprovalsummary` ADD COLUMN `auto_approved_updates` integer UNSIGNED NOT NULL;
