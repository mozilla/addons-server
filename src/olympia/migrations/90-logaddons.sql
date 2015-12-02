DROP TABLE IF EXISTS log_activity_addon;
DROP TABLE IF EXISTS log_activity_user;
DROP TABLE IF EXISTS log_activity;

CREATE TABLE `log_activity_addon` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `addon_id` integer UNSIGNED NOT NULL,
    `activity_log_id` integer NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8
;
ALTER TABLE `log_activity_addon` ADD CONSTRAINT `addon_id_refs_id_5bfa17d1` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
CREATE TABLE `log_activity_user` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `activity_log_id` integer NOT NULL,
    `user_id` integer UNSIGNED NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8
;
ALTER TABLE `log_activity_user` ADD CONSTRAINT `user_id_refs_id_e987c199` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);
CREATE TABLE `log_activity` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `user_id` integer UNSIGNED,
    `action` smallint NOT NULL,
    `arguments` longtext NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8
;
ALTER TABLE `log_activity` ADD CONSTRAINT `user_id_refs_id_3fa7a30a` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);
ALTER TABLE `log_activity_addon` ADD CONSTRAINT `activity_log_id_refs_id_9c20a926` FOREIGN KEY (`activity_log_id`) REFERENCES `log_activity` (`id`);
ALTER TABLE `log_activity_user` ADD CONSTRAINT `activity_log_id_refs_id_4f8d99d4` FOREIGN KEY (`activity_log_id`) REFERENCES `log_activity` (`id`);
CREATE INDEX `log_activity_addon_cc3d5937` ON `log_activity_addon` (`addon_id`);
CREATE INDEX `log_activity_addon_3bf68f54` ON `log_activity_addon` (`activity_log_id`);
CREATE INDEX `log_activity_user_3bf68f54` ON `log_activity_user` (`activity_log_id`);
CREATE INDEX `log_activity_user_fbfc09f1` ON `log_activity_user` (`user_id`);
CREATE INDEX `log_activity_fbfc09f1` ON `log_activity` (`user_id`);
CREATE INDEX `log_activity_1bd4707b` ON `log_activity` (`action`);
