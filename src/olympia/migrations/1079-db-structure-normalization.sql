/* only exists in prod */
DROP TABLE IF EXISTS `theme_user_counts_20170606`;

/* missing constraints on dev - manually added.  For reference if anyone wants to add locally.*/
/*
ALTER TABLE `abuse_reports`
    ADD CONSTRAINT `reporter_id_refs_id_12d88e23` FOREIGN KEY (`reporter_id`) REFERENCES `users` (`id`),
    ADD CONSTRAINT `user_id_refs_id_12d88e23` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `addons_collections`
    ADD CONSTRAINT `addons_collections_ibfk_3` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `addons_users`
    ADD CONSTRAINT `addons_users_ibfk_2` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `collections`
    ADD CONSTRAINT `collections_ibfk_7` FOREIGN KEY (`author_id`) REFERENCES `users` (`id`);

ALTER TABLE `editor_subscriptions`
    ADD CONSTRAINT `editor_subscriptions_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `file_uploads`
    ADD CONSTRAINT `file_uploads_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `update_counts`
    MODIFY `application` longtext;

ALTER TABLE `users`
    MODIFY `username` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
    MODIFY `notes` text,
    MODIFY `last_login_ip` char(45) CHARACTER SET utf8 NOT NULL DEFAULT '';
*/
