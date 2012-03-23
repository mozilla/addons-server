CREATE TABLE `addon_inapp_log` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `action` int(11) unsigned NOT NULL,
    `app_public_key` varchar(255) NULL,
    `session_key` varchar(64) NOT NULL,
    `user_id` int(11) unsigned NULL,
    `config_id` int(11) unsigned NULL,
    `exception` int(11) unsigned NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;
ALTER TABLE `addon_inapp_log` ADD CONSTRAINT `user_id_refs_id_8dae1945`
                    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);
ALTER TABLE `addon_inapp_log` ADD CONSTRAINT `config_id_refs_id_93ad9ec4`
                    FOREIGN KEY (`config_id`) REFERENCES `addon_inapp` (`id`);
CREATE INDEX `addon_inapp_log_fbfc09f1` ON `addon_inapp_log` (`user_id`);
CREATE INDEX `addon_inapp_log_c41bdac` ON `addon_inapp_log` (`config_id`);
