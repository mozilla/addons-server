CREATE TABLE `webapps_geodata` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `addon_id` int(11) unsigned NOT NULL UNIQUE,
    `restricted` bool NOT NULL,
    `popular_region` varchar(10)
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `webapps_geodata` ADD CONSTRAINT `webapps_geodata_addon_id_fk`
    FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`) ON DELETE CASCADE;
