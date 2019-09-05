ALTER TABLE `editor_subscriptions`
    MODIFY `addon_id` int(10) unsigned NOT NULL,
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    DROP KEY `user_id`,  /* (`user_id`),*/
    DROP KEY `addon_id`,  /* (`addon_id`),*/
    DROP FOREIGN KEY `editor_subscriptions_ibfk_1`,  /* (`user_id`) REFERENCES `users` (`id`),*/
    DROP FOREIGN KEY `editor_subscriptions_ibfk_2`, /* (`addon_id`) REFERENCES `addons` (`id`) ON DELETE CASCADE,*/
    ADD CONSTRAINT `editor_subscriptions_addon_id_8e6d8f62_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`),
    ADD CONSTRAINT `editor_subscriptions_user_id_89527849_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);
