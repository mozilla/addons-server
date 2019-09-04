ALTER TABLE `reviews`
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    MODIFY `id` int(10) unsigned NOT NULL,
    MODIFY `version_id` int(10) unsigned DEFAULT NULL,
    MODIFY `user_id` int(11) NOT NULL,
    MODIFY `reply_to` int(10) unsigned DEFAULT NULL,
    MODIFY `rating` smallint(5) unsigned DEFAULT NULL,
    MODIFY `editorreview` tinyint(1) NOT NULL,
    MODIFY `flag` tinyint(1) NOT NULL,
    MODIFY `ip_address` varchar(255) NOT NULL,
    MODIFY `addon_id` int(10) unsigned NOT NULL,
    MODIFY `previous_count` int(10) unsigned NOT NULL,
    MODIFY `is_latest` tinyint(1) NOT NULL,
    MODIFY `deleted` tinyint(1) NOT NULL,
    DROP FOREIGN KEY `reviews_ibfk_4`,  /* The fk for the body column */
    DROP FOREIGN KEY `reviews_ibfk_5`,  /* addons.id */
    DROP FOREIGN KEY `reviews_reply`,  /* reply_to fk */
    DROP FOREIGN KEY `reviews_ibfk_2`,  /* users.id */
    DROP FOREIGN KEY `reviews_ibfk_1`;  /* versions.id */
ALTER TABLE `reviews`
    DROP `body`,
    ADD CONSTRAINT `reviews_addon_id_80638543_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`),
    ADD CONSTRAINT `reviews_reply_to_3e3e5a19_fk_reviews_id` FOREIGN KEY (`reply_to`) REFERENCES `reviews` (`id`),
    ADD CONSTRAINT `reviews_user_id_c23b0903_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
    ADD CONSTRAINT `reviews_version_id_abde965e_fk_versions_id` FOREIGN KEY (`version_id`) REFERENCES `versions` (`id`);
