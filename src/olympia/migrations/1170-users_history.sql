/* There are some old entries in users_history which point to non-existent users, need to delete them to add the missing constraint */
DELETE FROM `users_history` USING `users_history`
    LEFT JOIN `users` ON `users_history`.`user_id` = `users`.`id`
    WHERE `users`.`id` IS NULL AND `users_history`.`user_id` IS NOT NULL;

ALTER TABLE `users_history`
    CHANGE COLUMN `user_id` `user_id` INT (11) NOT NULL,
    CHANGE COLUMN `created` `created` DATETIME (6) NOT NULL,
    CHANGE COLUMN `modified` `modified` DATETIME (6) NOT NULL,
    CHANGE COLUMN `id` `id` INT (10) UNSIGNED NOT NULL AUTO_INCREMENT,
    CHANGE COLUMN `email` `email` VARCHAR (75) NOT NULL,
    ADD INDEX `users_history_user_id_358ca354_fk_users_id` (`user_id`),
    ADD CONSTRAINT `users_history_user_id_358ca354_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);
