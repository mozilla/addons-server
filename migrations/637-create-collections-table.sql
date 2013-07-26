CREATE TABLE `app_collections` (
    `id` int(11) UNSIGNED AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `collection_type` tinyint(1) UNSIGNED NOT NULL,
    `description` int(11) UNSIGNED NOT NULL,
    `name` int(11) UNSIGNED NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

CREATE TABLE `app_collection_membership` (
    `id` int(11) UNSIGNED AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `collection_id` int(11) UNSIGNED NOT NULL,
    `app_id` int(11) UNSIGNED NOT NULL,
    `order` tinyint(1) UNSIGNED NOT NULL,
    UNIQUE (`collection_id`, `app_id`)
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `app_collections` ADD CONSTRAINT `app_collection_name_translation_id` FOREIGN KEY (`name`) REFERENCES `translations` (`id`);
ALTER TABLE `app_collections` ADD CONSTRAINT `app_collection_description_translation_id` FOREIGN KEY (`description`) REFERENCES `translations` (`id`);
ALTER TABLE `app_collection_membership` ADD CONSTRAINT `app_collection_membership_app_id` FOREIGN KEY (`app_id`) REFERENCES `addons` (`id`);
ALTER TABLE `app_collection_membership` ADD CONSTRAINT `app_collection_membership_collection_id` FOREIGN KEY (`collection_id`) REFERENCES `app_collections` (`id`);
