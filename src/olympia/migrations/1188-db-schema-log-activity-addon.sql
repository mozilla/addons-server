ALTER TABLE `log_activity_addon`
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    DROP KEY `log_activity_addon_3bf68f54`,  /* (`activity_log_id`),*/
    DROP FOREIGN KEY `activity_log_id_refs_id_9c20a926`,  /* (`activity_log_id`) REFERENCES `log_activity` (`id`) ON DELETE CASCADE,*/
    DROP KEY `log_activity_addon_cc3d5937`,  /* (`addon_id`),*/
    DROP FOREIGN KEY `addon_id_refs_id_5bfa17d1`,  /* (`addon_id`) REFERENCES `addons` (`id`) ON DELETE CASCADE*/
    ADD KEY `log_activity_addon_activity_log_id_1b973cff_fk_log_activity_id` (`activity_log_id`),
    ADD CONSTRAINT `log_activity_addon_activity_log_id_1b973cff_fk_log_activity_id` FOREIGN KEY (`activity_log_id`) REFERENCES `log_activity` (`id`),
    ADD KEY `log_activity_addon_addon_id_f4600a29_fk_addons_id` (`addon_id`),
    ADD CONSTRAINT `log_activity_addon_addon_id_f4600a29_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
