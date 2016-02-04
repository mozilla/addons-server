CREATE TABLE `ratings` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `addon_id` int(11) unsigned NOT NULL,
    `user_id` int(11) unsigned NOT NULL,
    `reply_to` int(11) unsigned UNIQUE,
    `score` smallint UNSIGNED,
    `body` int(11) unsigned UNIQUE,
    `ip_address` varchar(255) NOT NULL,
    `editorreview` bool NOT NULL,
    `flag` bool NOT NULL,
    `is_latest` bool NOT NULL,
    `previous_count` integer UNSIGNED NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `ratings`
    ADD CONSTRAINT `ratings_addon_id_fk`
    FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
ALTER TABLE `ratings`
    ADD CONSTRAINT `ratings_user_id_fk`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);
ALTER TABLE `ratings`
    ADD CONSTRAINT `ratings_body_fk`
    FOREIGN KEY (`body`) REFERENCES `translations` (`id`);
ALTER TABLE `ratings`
    ADD CONSTRAINT `ratings_reply_to_fk3`
    FOREIGN KEY (`reply_to`) REFERENCES `ratings` (`id`);

CREATE TABLE `ratings_moderation_flags` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `rating_id` int(11) unsigned NOT NULL,
    `user_id` int(11) unsigned NOT NULL,
    `flag_name` varchar(64) NOT NULL,
    `flag_notes` varchar(100) NOT NULL,
    UNIQUE (`rating_id`, `user_id`)
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `ratings_moderation_flags`
    ADD CONSTRAINT `ratings_moderation_flags_rating_id_fk`
    FOREIGN KEY (`rating_id`) REFERENCES `ratings` (`id`);
ALTER TABLE `ratings_moderation_flags`
    ADD CONSTRAINT `ratings_moderation_flags_user_id_fk`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

CREATE INDEX `ratings_addon_id_idx` ON `ratings` (`addon_id`);
CREATE INDEX `ratings_user_id_idx` ON `ratings` (`user_id`);
CREATE INDEX `ratings_moderation_flags_rating_id_idx` ON `ratings_moderation_flags` (`rating_id`);
CREATE INDEX `ratings_moderation_flags_user_id_idx` ON `ratings_moderation_flags` (`user_id`);
