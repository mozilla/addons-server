ALTER TABLE `addons`
    ADD COLUMN `admin_review_type` tinyint(1) unsigned NOT NULL default '1' AFTER `adminreview`;