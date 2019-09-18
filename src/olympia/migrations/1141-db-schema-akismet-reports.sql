ALTER TABLE `akismet_reports`
    MODIFY `rating_instance_id` int(10) unsigned DEFAULT NULL,
    MODIFY `addon_instance_id` int(10) unsigned DEFAULT NULL,
    MODIFY `collection_instance_id` int(10) unsigned DEFAULT NULL,
    MODIFY `user_id` int(11) DEFAULT NULL,
    DROP FOREIGN KEY `akismet_reports_addon_instance_id_fk_addons_id`,
    DROP FOREIGN KEY `akismet_reports_collection_instance_id_fk_collections_id`,
    DROP FOREIGN KEY `akismet_reports_upload_instance_id_fk_file_uploads_id`,
    DROP FOREIGN KEY `akismet_reports_user_id_fk_users_id`,
    ADD CONSTRAINT `akismet_reports_addon_instance_id_03f471af_fk_addons_id` FOREIGN KEY (`addon_instance_id`) REFERENCES `addons` (`id`),
    ADD CONSTRAINT `akismet_reports_collection_instance__2c06adf6_fk_collectio` FOREIGN KEY (`collection_instance_id`) REFERENCES `collections` (`id`),
    ADD CONSTRAINT `akismet_reports_upload_instance_id_c4530dc1_fk_file_uploads_id` FOREIGN KEY (`upload_instance_id`) REFERENCES `file_uploads` (`id`),
    ADD CONSTRAINT `akismet_reports_user_id_97ce80b4_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);
