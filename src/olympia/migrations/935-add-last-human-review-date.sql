TRUNCATE TABLE `addons_addonapprovalscounter`;
ALTER TABLE `addons_addonapprovalscounter` ADD COLUMN `last_human_review` datetime(6);
