CREATE TABLE `users_userrestrictionhistory` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime(6) NOT NULL,
    `modified` datetime(6) NOT NULL,
    `restriction` smallint UNSIGNED NOT NULL,
    `ip_address` varchar(45) NOT NULL,
    `last_login_ip` varchar(45) NOT NULL,
    `user_id` integer NOT NULL
);
ALTER TABLE `users_userrestrictionhistory` ADD CONSTRAINT `users_userrestrictionhistory_user_id_a8dc535c_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);
