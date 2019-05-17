CREATE TABLE `users_user_restriction` (
  `id` integer UNSIGNED AUTO_INCREMENT NOT NULL PRIMARY KEY,
  `created` datetime(6) NOT NULL,
  `modified` datetime(6) NOT NULL,
  `ip_address` char(39) DEFAULT NULL,
  `network` char(45) DEFAULT NULL,
  `email` varchar(75) DEFAULT NULL,
);
