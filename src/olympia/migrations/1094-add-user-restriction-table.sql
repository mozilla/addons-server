CREATE TABLE `users_user_ip_restriction` (
  `id` integer UNSIGNED AUTO_INCREMENT NOT NULL PRIMARY KEY,
  `created` datetime(6) NOT NULL,
  `modified` datetime(6) NOT NULL,
  `ip_address` char(39) DEFAULT NULL,
);

CREATE TABLE `users_user_network_restriction` (
  `id` integer UNSIGNED AUTO_INCREMENT NOT NULL PRIMARY KEY,
  `created` datetime(6) NOT NULL,
  `modified` datetime(6) NOT NULL,
  `network` char(45) DEFAULT NULL,
);

CREATE TABLE `users_user_email_restriction` (
  `id` integer UNSIGNED AUTO_INCREMENT NOT NULL PRIMARY KEY,
  `created` datetime(6) NOT NULL,
  `modified` datetime(6) NOT NULL,
  `email` varchar(75) DEFAULT NULL,
);
