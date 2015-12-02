ALTER TABLE `webapps_geodata`
ADD COLUMN `banner_message` int(11) unsigned DEFAULT NULL,
ADD CONSTRAINT `webapps_geodata_banner_message_id` FOREIGN KEY (`banner_message`) REFERENCES `translations` (`id`) ON DELETE SET NULL;

ALTER TABLE `webapps_geodata`
ADD COLUMN `banner_regions` longtext DEFAULT NULL;
