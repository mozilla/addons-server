CREATE TABLE `users_history` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `email` varchar(75) UNIQUE,
    `user_id` int(11) unsigned NOT NULL
)ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

CREATE INDEX `users_history_user_idx` ON `users_history` (`user_id`);
