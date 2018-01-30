ALTER TABLE `addons_addonreviewerflags` ADD COLUMN `auto_approval_disabled` bool NOT NULL DEFAULT false;
ALTER TABLE `editors_autoapprovalsummary` ADD COLUMN `has_auto_approval_disabled` bool NOT NULL DEFAULT false;
