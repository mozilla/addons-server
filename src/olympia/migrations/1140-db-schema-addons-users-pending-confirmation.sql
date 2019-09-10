ALTER TABLE `addons_users_pending_confirmation`
    DROP FOREIGN KEY `addons_users_pending_confirmation_addon_id_9e12bbad_fk_addons_id`,
    DROP FOREIGN KEY `addons_users_pending_confirmation_user_id_3c4c2421_fk_users_id`,
    ADD CONSTRAINT `addons_users_pending_confirmation_addon_id_a28f2247_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`),
    ADD CONSTRAINT `addons_users_pending_confirmation_user_id_a9a86f72_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);
