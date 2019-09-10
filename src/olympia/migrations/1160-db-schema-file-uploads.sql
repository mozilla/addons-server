ALTER TABLE `file_uploads`
    MODIFY `id` int(11) NOT NULL AUTO_INCREMENT,
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    MODIFY `hash` varchar(255) NOT NULL,
    MODIFY `valid` tinyint(1) NOT NULL,
    MODIFY `compat_with_app_id` int(10) unsigned DEFAULT NULL,
    MODIFY `compat_with_appver_id` int(10) unsigned DEFAULT NULL,
    MODIFY `automated_signing` tinyint(1) NOT NULL,
    MODIFY `addon_id` int(10) unsigned DEFAULT NULL,
    DROP KEY `file_uploads_9a93262a`,  /* (`compat_with_appver_id`),*/
    DROP FOREIGN KEY `compat_with_appver_id_refs_id_3747a309`,  /* (`compat_with_appver_id`) REFERENCES `appversions` (`id`), */
    ADD KEY `file_uploads_compat_with_appver_id_d3fafb87_fk_appversions_id` (`compat_with_appver_id`),
    ADD CONSTRAINT `file_uploads_compat_with_appver_id_d3fafb87_fk_appversions_id` FOREIGN KEY (`compat_with_appver_id`) REFERENCES `appversions` (`id`),
    DROP KEY `file_uploads_refs_addon_id`,  /* (`addon_id`),*/
    DROP FOREIGN KEY `file_uploads_refs_addon_id`,  /*(`addon_id`) REFERENCES `addons` (`id`)*/
    ADD KEY `file_uploads_addon_id_931d50e2_fk_addons_id` (`addon_id`),
    ADD CONSTRAINT `file_uploads_addon_id_931d50e2_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`),
    DROP KEY `user_id`,  /* (`user_id`),*/
    DROP FOREIGN KEY `file_uploads_ibfk_1`,  /* (`user_id`) REFERENCES `users` (`id`), */
    ADD KEY `file_uploads_user_id_a685214a_fk_users_id` (`user_id`),
    ADD CONSTRAINT `file_uploads_user_id_a685214a_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);
