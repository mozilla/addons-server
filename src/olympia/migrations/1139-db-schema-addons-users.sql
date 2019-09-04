ALTER TABLE `addons_users`
    MODIFY `addon_id` int(10) unsigned NOT NULL,
    MODIFY `user_id` int(11) NOT NULL,
    MODIFY `role` smallint(6) NOT NULL,
    MODIFY `listed` tinyint(1) NOT NULL,
    MODIFY `position` int(11) NOT NULL,
    DROP FOREIGN KEY `addons_users_ibfk_1`,  /* `addon_id` */
    DROP FOREIGN KEY `addons_users_ibfk_2`,  /* `user_id` */
    ADD CONSTRAINT `addons_users_addon_id_cfbb3174_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`),
    ADD CONSTRAINT `addons_users_user_id_411d394c_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);
