CREATE TABLE `users_blacklistedpassword` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `password` varchar(255) NOT NULL UNIQUE
);

