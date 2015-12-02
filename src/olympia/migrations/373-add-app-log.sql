CREATE TABLE `log_activity_app` (
    `id` int(11) UNSIGNED AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `addon_id` integer NOT NULL,
    `activity_log_id` integer NOT NULL,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE utf8_general_ci;
ALTER TABLE `log_activity_app` ADD CONSTRAINT `log_activity_app_activity_log_id_key` FOREIGN KEY (`activity_log_id`) REFERENCES `log_activity` (`id`);
