ALTER TABLE `log_activity_tokens`
    MODIFY `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    MODIFY `version_id` int(10) unsigned NOT NULL,
    MODIFY `use_count` int(11) NOT NULL,
    DROP KEY `log_activity_tokens_user`,  /* (`user_id`),*/
    DROP FOREIGN KEY `log_activity_tokens_user`,  /* (`user_id`) REFERENCES `users` (`id`),*/
    DROP FOREIGN KEY `log_activity_tokens_version`,  /* (`version_id`) REFERENCES `versions` (`id`)*/
    ADD KEY `log_activity_tokens_user_id_e3a89b6f_fk_users_id` (`user_id`),
    ADD CONSTRAINT `log_activity_tokens_user_id_e3a89b6f_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
    ADD CONSTRAINT `log_activity_tokens_version_id_8357c920_fk_versions_id` FOREIGN KEY (`version_id`) REFERENCES `versions` (`id`);
