ALTER TABLE `blapps` ADD COLUMN `blplugin_id` int(11) unsigned DEFAULT NULL;

ALTER TABLE `blapps` ADD CONSTRAINT `blplugin_id_apps` FOREIGN KEY (`blplugin_id`) REFERENCES `blplugins` (`id`);

ALTER TABLE `blapps` MODIFY `blitem_id` int(11) unsigned DEFAULT NULL;
