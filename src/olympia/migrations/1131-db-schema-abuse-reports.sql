ALTER TABLE `abuse_reports`
    MODIFY `addon_id` int(10) unsigned DEFAULT NULL,
    DROP FOREIGN KEY `reporter_id_refs_id_12d88e23`,
    DROP FOREIGN KEY `user_id_refs_id_12d88e23`,
    DROP FOREIGN KEY `addon_id_refs_id_2b6ff2a7`,
    ADD CONSTRAINT `abuse_reports_addon_id_f15faa13_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`),
    ADD CONSTRAINT `abuse_reports_reporter_id_e5b6b72a_fk_users_id` FOREIGN KEY (`reporter_id`) REFERENCES `users` (`id`),
    ADD CONSTRAINT `abuse_reports_user_id_67401662_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);
