CREATE TABLE `log_activity_app_mkt` (
    `id` int(11) NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `addon_id` int(11) NOT NULL,
    `activity_log_id` int(11) NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `log_activity_app_mkt` AUTO_INCREMENT = 5000000;

CREATE TABLE `log_activity_comment_mkt` (
    `id` int(11) NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `activity_log_id` int(11) NOT NULL,
    `comments` longtext NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `log_activity_comment_mkt` AUTO_INCREMENT = 5000000;

CREATE TABLE `log_activity_version_mkt` (
    `id` int(11) NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `activity_log_id` int(11) NOT NULL,
    `version_id` int(11) unsigned NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `log_activity_version_mkt` AUTO_INCREMENT = 5000000;
ALTER TABLE `log_activity_version_mkt` ADD CONSTRAINT `version_id_refs_id_e1ef9328` FOREIGN KEY (`version_id`) REFERENCES `versions` (`id`);

CREATE TABLE `log_activity_user_mkt` (
    `id` int(11) NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `activity_log_id` int(11) NOT NULL,
    `user_id` int(11) unsigned NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;


ALTER TABLE `log_activity_user_mkt` AUTO_INCREMENT = 5000000;
ALTER TABLE `log_activity_user_mkt` ADD CONSTRAINT `user_id_refs_id_2eb55c34` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

CREATE TABLE `log_activity_mkt` (
    `id` int(11) NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `user_id` int(1) unsigned DEFAULT NULL,
    `action` smallint(6) NOT NULL,
    `arguments` longtext NOT NULL,
    `details` longtext NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;


ALTER TABLE `log_activity_mkt` AUTO_INCREMENT = 5000000;
ALTER TABLE `log_activity_mkt` ADD CONSTRAINT `user_id_refs_user_id_ee305b55` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);
ALTER TABLE `log_activity_app_mkt` ADD CONSTRAINT `activity_log_id_refs_id_d08a7a0f` FOREIGN KEY (`activity_log_id`) REFERENCES `log_activity_mkt` (`id`);
ALTER TABLE `log_activity_comment_mkt` ADD CONSTRAINT `activity_log_id_refs_id_8c3808d7` FOREIGN KEY (`activity_log_id`) REFERENCES `log_activity_mkt` (`id`);
ALTER TABLE `log_activity_version_mkt` ADD CONSTRAINT `activity_log_id_refs_id_f626a650` FOREIGN KEY (`activity_log_id`) REFERENCES `log_activity_mkt` (`id`);
ALTER TABLE `log_activity_user_mkt` ADD CONSTRAINT `activity_log_id_refs_id_fbabd042` FOREIGN KEY (`activity_log_id`) REFERENCES `log_activity_mkt` (`id`);
