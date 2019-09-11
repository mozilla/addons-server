ALTER TABLE `log_activity_user`
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    DROP KEY `log_activity_user_3bf68f54`,  /* (`activity_log_id`),*/
    DROP KEY `log_activity_user_fbfc09f1`,  /* (`user_id`),*/
    DROP FOREIGN KEY `activity_log_id_refs_id_4f8d99d4`,  /* (`activity_log_id`) REFERENCES `log_activity` (`id`) ON DELETE CASCADE,*/
    DROP FOREIGN KEY `user_id_refs_id_e987c199`,  /* (`user_id`) REFERENCES `users` (`id`)*/
    ADD KEY `log_activity_user_activity_log_id_c691f1a5_fk_log_activity_id` (`activity_log_id`),
    ADD KEY `log_activity_user_user_id_c0bca5cf_fk_users_id` (`user_id`),
    ADD CONSTRAINT `log_activity_user_activity_log_id_c691f1a5_fk_log_activity_id` FOREIGN KEY (`activity_log_id`) REFERENCES `log_activity` (`id`),
    ADD CONSTRAINT `log_activity_user_user_id_c0bca5cf_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);
