ALTER TABLE `groups_users`
    MODIFY `group_id` int(10) unsigned NOT NULL,
    MODIFY `user_id` int(11) NOT NULL,
    DROP KEY `user_id`,
    DROP FOREIGN KEY `groups_users_ibfk_4`,  /* (`user_id`) REFERENCES `users` (`id`)*/
    DROP FOREIGN KEY `groups_users_ibfk_3`,  /* (`group_id`) REFERENCES `groups` (`id`) ON DELETE CASCADE,*/
    ADD KEY `groups_users_user_id_97bd0715_fk_users_id` (`user_id`),
    ADD CONSTRAINT `groups_users_user_id_97bd0715_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
    ADD KEY `groups_users_group_id_9b6cc385_fk_groups_id` (`group_id`),
    ADD CONSTRAINT `groups_users_group_id_9b6cc385_fk_groups_id` FOREIGN KEY (`group_id`) REFERENCES `groups` (`id`);
