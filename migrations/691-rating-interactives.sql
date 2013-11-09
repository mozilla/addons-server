CREATE TABLE `webapps_rating_interactives` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `addon_id` int(11) unsigned NOT NULL UNIQUE,
    `has_users_interact` bool NOT NULL,
    `has_shares_info` bool NOT NULL,
    `has_shares_location` bool NOT NULL,
    `has_digital_purchases` bool NOT NULL,
    `has_digital_content_portal` bool NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `webapps_rating_interactives` ADD CONSTRAINT `rating_interactives_addon_id_key`
FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`) ON DELETE CASCADE;
