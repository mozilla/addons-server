ALTER TABLE `reviews_moderation_flags`
    DROP FOREIGN KEY `reviews_moderation_flags_ibfk_2`,
    DROP FOREIGN KEY `reviews_moderation_flags_ibfk_1`,
    CHANGE COLUMN `created` `created` DATETIME (6) NOT NULL,
    CHANGE COLUMN `modified` `modified` DATETIME (6) NOT NULL,
    CHANGE COLUMN `review_id` `review_id` INT (10) UNSIGNED NOT NULL,
    CHANGE COLUMN `flag_name` `flag_name` VARCHAR (64) NOT NULL,
    CHANGE COLUMN `flag_notes` `flag_notes` VARCHAR (100) NOT NULL,
    ADD CONSTRAINT `reviews_moderation_flags_user_id_1d97f36e_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
    ADD CONSTRAINT `reviews_moderation_flags_review_id_3201518d_fk_reviews_id` FOREIGN KEY (`review_id`) REFERENCES `reviews` (`id`);
