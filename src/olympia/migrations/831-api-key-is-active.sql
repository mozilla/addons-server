ALTER TABLE `api_key`
    ADD COLUMN `is_active` tinyint(1) unsigned NOT NULL default '1',
    ADD COLUMN `created` datetime NOT NULL,
    ADD COLUMN `modified` datetime NOT NULL;
