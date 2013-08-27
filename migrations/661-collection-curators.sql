CREATE TABLE `app_collections_curators` (
    `id` int(11) UNSIGNED AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `collection_id` int(11) UNSIGNED NOT NULL,
    `userprofile_id` int(11) UNSIGNED NOT NULL,
    UNIQUE (`collection_id`, `userprofile_id`)
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `app_collections_curators` ADD CONSTRAINT `app_collections_curators_userprofile_id` FOREIGN KEY (`userprofile_id`) REFERENCES `users` (`id`);
ALTER TABLE `app_collections_curators` ADD CONSTRAINT `app_collections_curators_collection_id` FOREIGN KEY (`collection_id`) REFERENCES `app_collections` (`id`);
