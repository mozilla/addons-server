CREATE TABLE `webapps_contentrating` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `addon_id` int(11) unsigned NOT NULL,
    `ratings_body` integer UNSIGNED NOT NULL,
    `rating` integer UNSIGNED NOT NULL
    ) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

;
ALTER TABLE `webapps_contentrating` ADD CONSTRAINT `addon_id_refs_id_4fa22f5e` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
