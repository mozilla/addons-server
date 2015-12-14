CREATE TABLE `api_key` (
    `id` int(11) UNSIGNED AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `user_id` int(11) NOT NULL,
    `type` int(11) UNSIGNED NOT NULL DEFAULT 1,
    `key` varchar(255) NOT NULL UNIQUE,
    `secret` LONGTEXT NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `api_key` ADD CONSTRAINT `api_key_user_id`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);
