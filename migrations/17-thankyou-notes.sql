ALTER TABLE `addons`
    ADD COLUMN `thankyou_note` int(11) unsigned default NULL AFTER `wants_contributions`,
    ADD COLUMN `enable_thankyou` tinyint(1) unsigned NOT NULL default '0' AFTER `wants_contributions`,
    ADD KEY `addons_ibfk_13` (`thankyou_note`),
    ADD CONSTRAINT `addons_ibfk_13` FOREIGN KEY (`thankyou_note`) REFERENCES `translations` (`id`);

ALTER TABLE `stats_contributions`
    ADD COLUMN `source_locale` varchar(10) default NULL AFTER `source`;
