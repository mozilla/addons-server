ALTER TABLE `akismet_reports`
  MODIFY `content_link` varchar(255) DEFAULT NULL,
  MODIFY `content_modified` datetime(6) DEFAULT NULL,
  ADD COLUMN `user_id` int(11) DEFAULT NULL,
  ADD COLUMN `addon_instance_id` int(11) unsigned DEFAULT NULL,
  ADD COLUMN `upload_instance_id` int(11) DEFAULT NULL,
  ADD COLUMN`collection_instance_id` int(11) unsigned DEFAULT NULL,

  ADD KEY `akismet_reports_user_id_fk_users_id` (`user_id`),
  ADD CONSTRAINT `akismet_reports_user_id_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),

  ADD KEY `akismet_reports_addon_instance_id_fk_addons_id` (`addon_instance_id`),
  ADD CONSTRAINT `akismet_reports_addon_instance_id_fk_addons_id` FOREIGN KEY (`addon_instance_id`) REFERENCES `addons` (`id`),

  ADD KEY `akismet_reports_upload_instance_id_fk_file_uploads_id` (`upload_instance_id`),
  ADD CONSTRAINT `akismet_reports_upload_instance_id_fk_file_uploads_id` FOREIGN KEY (`upload_instance_id`) REFERENCES `file_uploads` (`id`),

  ADD KEY `akismet_reports_collection_instance_id_fk_collections_id` (`collection_instance_id`),
  ADD CONSTRAINT `akismet_reports_collection_instance_id_fk_collections_id` FOREIGN KEY (`collection_instance_id`) REFERENCES `collections` (`id`)
;
