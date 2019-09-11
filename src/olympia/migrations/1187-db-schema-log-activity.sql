ALTER TABLE `log_activity`
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    MODIFY `details` longtext NOT NULL,
    DROP KEY `log_activity_fbfc09f1`,  /* (`user_id`),*/
    DROP FOREIGN KEY `user_id_refs_id_3fa7a30a`,  /* (`user_id`) REFERENCES `users` (`id`)*/
    ADD KEY `log_activity_user_id_6ed3455e_fk_users_id` (`user_id`),
    ADD CONSTRAINT `log_activity_user_id_6ed3455e_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);
