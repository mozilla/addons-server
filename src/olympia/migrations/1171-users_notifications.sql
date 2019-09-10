ALTER TABLE `users_notifications`
    DROP FOREIGN KEY `users_notifications_ibfk_1`,
    CHANGE   COLUMN `modified` `modified` DATETIME (6) NOT NULL,
    CHANGE COLUMN `enabled` `enabled` TINYINT (1) NOT NULL,
    CHANGE COLUMN `created` `created` DATETIME (6) NOT NULL,
    ADD INDEX `users_notifications_user_id_d8bb60d3_fk_users_id` (`user_id`),
    ADD CONSTRAINT `users_notifications_user_id_d8bb60d3_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);
