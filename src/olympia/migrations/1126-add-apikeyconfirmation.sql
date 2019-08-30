CREATE TABLE `api_apikeyconfirmation` (
    `created` datetime(6) NOT NULL,
    `modified` datetime(6) NOT NULL,
    `user_id` integer NOT NULL PRIMARY KEY,
    `token` varchar(20) NOT NULL,
    `confirmed_once` bool NOT NULL
);
ALTER TABLE `api_apikeyconfirmation` ADD CONSTRAINT `api_apikeyconfirmation_user_id_2b790b05_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);
