CREATE TABLE `api_access` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `key` varchar(255) NOT NULL UNIQUE,
    `secret` varchar(255) NOT NULL,
    `user_id` int(11) NOT NULL
    -- Note: this type matches auth_user.id
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `api_access` ADD CONSTRAINT `user_id_api` FOREIGN KEY (`user_id`) REFERENCES `auth_user` (`id`);
CREATE INDEX `api_access_user` ON `api_access` (`user_id`);
