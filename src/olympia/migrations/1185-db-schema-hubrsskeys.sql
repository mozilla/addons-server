ALTER TABLE `hubrsskeys`
    MODIFY `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
    MODIFY `addon_id` int(10) unsigned DEFAULT NULL,
    MODIFY `created` date NOT NULL,
    DROP FOREIGN KEY `hubrsskeys_ibfk_1`,  /* (`user_id`) REFERENCES `users` (`id`),*/
    DROP FOREIGN KEY `hubrsskeys_ibfk_2`,  /* (`addon_id`) REFERENCES `addons` (`id`) ON DELETE CASCADE*/
    ADD CONSTRAINT `hubrsskeys_addon_id_ce909c47_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`),
    ADD CONSTRAINT `hubrsskeys_user_id_4a5b5b26_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);
