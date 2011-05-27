CREATE TABLE `users_blacklistedpassword` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `password` varchar(255) NOT NULL UNIQUE
);

INSERT INTO `users_blacklistedpassword` (created, modified, password)
    VALUE ('2011-05-27', '2011-05-27', 'password');
INSERT INTO `users_blacklistedpassword` (created, modified, password)
    VALUE ('2011-05-27', '2011-05-27', '12345678');
