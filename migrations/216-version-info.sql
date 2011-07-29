ALTER TABLE `versions`
    ADD COLUMN `has_editor_comment` tinyint(1) unsigned NOT NULL default '0',
    ADD COLUMN `has_info_request` tinyint(1) unsigned NOT NULL default '0';
