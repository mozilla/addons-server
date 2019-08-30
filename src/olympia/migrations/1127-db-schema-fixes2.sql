ALTER TABLE `addons_users`
    MODIFY `addon_id` int(10) unsigned NOT NULL,
    MODIFY `user_id` int(11) NOT NULL,
    MODIFY `role` smallint(6) NOT NULL,
    MODIFY `listed` tinyint(1) NOT NULL,
    MODIFY `position` int(11) NOT NULL,
    DROP UNIQUE KEY `addon_id`,
    DROP KEY `user_id`,
    DROP KEY `listed`,
    DROP KEY `addon_user_listed_idx`,  /* (`addon_id`,`user_id`,`listed`) - note: no replacement */
    DROP KEY `addon_listed_idx`,  /* (`addon_id`,`listed`) - note: no replacement */
    DROP FOREIGN KEY `addons_users_ibfk_1`,  /* `addon_id` */
    DROP FOREIGN KEY `addons_users_ibfk_2`;  /* `user_id` */
ALTER TABLE `addons_users`
    ADD UNIQUE KEY `addons_users_addon_id_user_id_0665ad00_uniq` (`addon_id`,`user_id`),
    ADD KEY `addons_users_user_id_411d394c` (`user_id`),
    ADD CONSTRAINT `addons_users_addon_id_cfbb3174_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`),
    ADD CONSTRAINT `addons_users_user_id_411d394c_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `addons_users_pending_confirmation`
    DROP KEY `addons_users_pending_confirmation_user_id_3c4c2421_fk_users_id`,
    DROP FOREIGN KEY `addons_users_pending_confirmation_addon_id_9e12bbad_fk_addons_id`,
    DROP FOREIGN KEY `addons_users_pending_confirmation_user_id_3c4c2421_fk_users_id`;
ALTER TABLE  `addons_users_pending_confirmation`
    ADD KEY `addons_users_pending_confirmation_user_id_a9a86f72` (`user_id`),
    ADD CONSTRAINT `addons_users_pending_confirmation_addon_id_a28f2247_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`),
    ADD CONSTRAINT `addons_users_pending_confirmation_user_id_a9a86f72_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `akismet_reports`
    MODIFY `rating_instance_id` int(10) unsigned DEFAULT NULL,
    MODIFY `addon_instance_id` int(10) unsigned DEFAULT NULL,
    MODIFY `collection_instance_id` int(10) unsigned DEFAULT NULL,
    MODIFY `user_id` int(11) DEFAULT NULL,
    DROP FOREIGN KEY `akismet_reports_addon_instance_id_fk_addons_id`,
    DROP FOREIGN KEY `akismet_reports_collection_instance_id_fk_collections_id`,
    DROP FOREIGN KEY `akismet_reports_upload_instance_id_fk_file_uploads_id`,
    DROP FOREIGN KEY `akismet_reports_user_id_fk_users_id`;
ALTER TABLE akismet_reports`
    ADD CONSTRAINT `akismet_reports_addon_instance_id_03f471af_fk_addons_id` FOREIGN KEY (`addon_instance_id`) REFERENCES `addons` (`id`),
    ADD CONSTRAINT `akismet_reports_collection_instance__2c06adf6_fk_collectio` FOREIGN KEY (`collection_instance_id`) REFERENCES `collections` (`id`),
    ADD CONSTRAINT `akismet_reports_upload_instance_id_c4530dc1_fk_file_uploads_id` FOREIGN KEY (`upload_instance_id`) REFERENCES `file_uploads` (`id`),
    ADD CONSTRAINT `akismet_reports_user_id_97ce80b4_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `api_key`
    MODIFY `id` int(10) unsigned NOT NULL,
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    MODIFY `type` int(10) unsigned NOT NULL,
    DROP KEY `user_id`,
    DROP KEY `api_key_user_id`,
    DROP FOREIGN KEY `api_key_user_id`;
ALTER TABLE `api_key`
    ADD UNIQUE KEY `api_key_user_id_is_active_96918b5d_uniq` (`user_id`,`is_active`),
    ADD CONSTRAINT `api_key_user_id_2b8305f7_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `applications_versions`
    MODIFY `application_id` int(10) unsigned NOT NULL,
    MODIFY `version_id` int(10) unsigned NOT NULL,
    MODIFY `min` int(10) unsigned NOT NULL,
    MODIFY `max` int(10) unsigned NOT NULL,
    DROP FOREIGN KEY `applications_versions_ibfk_4`,  /* `version_id` */
    DROP FOREIGN KEY `applications_versions_ibfk_5`,  /* `min` */
    DROP FOREIGN KEY `applications_versions_ibfk_6`,  /* `max` */
    DROP KEY `application_id`;
ALTER TABLE `applications_versions`
    ADD CONSTRAINT `applications_versions_version_id_9bf048e6_fk_versions_id` FOREIGN KEY (`version_id`) REFERENCES `versions` (`id`)
    ADD CONSTRAINT `applications_versions_min_1c31b27c_fk_appversions_id` FOREIGN KEY (`min`) REFERENCES `appversions` (`id`),
    ADD CONSTRAINT `applications_versions_max_6e57db5a_fk_appversions_id` FOREIGN KEY (`max`) REFERENCES `appversions` (`id`),
    ADD UNIQUE KEY `applications_versions_application_id_version_id_346c3b79_uniq` (`application_id`,`version_id`),

ALTER TABLE `appsupport`
    MODIFY `id` int(10) unsigned NOT NULL,
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    MODIFY `addon_id` int(10) unsigned NOT NULL,
    MODIFY `app_id` int(10) unsigned NOT NULL,
    MODIFY `min` bigint(20) DEFAULT NULL,
    MODIFY `max` bigint(20) DEFAULT NULL,
    DROP KEY `addon_id`,  /* (`addon_id`,`app_id`), */
    DROP KEY `app_id_refs_id_481ce338`,  /* (`app_id`)  note: there's the key, but no existing fk constraint */
    DROP KEY `minmax_idx`;  /* (`addon_id`,`app_id`,`min`,`max`) note: no replacment */
ALTER TABLE `appsupport`
    ADD UNIQUE KEY `appsupport_addon_id_app_id_8a82b814_uniq` (`addon_id`,`app_id`),
    ADD CONSTRAINT `appsupport_addon_id_a4820965_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);

ALTER TABLE `appversions`
    MODIFY `id` int(10) unsigned NOT NULL,
    MODIFY `application_id` int(10) unsigned NOT NULL,
    MODIFY `version` varchar(255) NOT NULL,
    MODIFY `version_int` bigint(20) NOT NULL,
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    DROP KEY `application_id`,  /* (`application_id`) */
    DROP KEY `version`,  /* (`version`)  */
    DROP KEY `version_int_idx`,  /* (`version_int`)*/
    DROP KEY `application_id_2`;  /* (`application_id`,`version`), */
ALTER TABLE `appversions`
    ADD UNIQUE KEY `appversions_application_id_version_5fe961bc_uniq` (`application_id`,`version`);

ALTER TABLE `auth_group`
    MODIFY `name` varchar(150) NOT NULL;

ALTER TABLE `auth_group_permissions`
    DROP FOREIGN KEY `group_id_refs_id_3cea63fe`,  /* `group_id` */
    DROP FOREIGN KEY `permission_id_refs_id_5886d21f`,  /* `permission_id` */
    DROP KEY `group_id`,  /* (`group_id`,`permission_id`), */
    DROP KEY `auth_group_permissions_group_id`,
    DROP KEY `auth_group_permissions_permission_id`;
ALTER TABLE `auth_group_permissions`
    ADD CONSTRAINT `auth_group_permissions_group_id_b120cbf9_fk_auth_group_id` FOREIGN KEY (`group_id`) REFERENCES `auth_group` (`id`),
    ADD CONSTRAINT `auth_group_permissio_permission_id_84c5c92e_fk_auth_perm` FOREIGN KEY (`permission_id`) REFERENCES `auth_permission` (`id`),
    ADD UNIQUE KEY `auth_group_permissions_group_id_permission_id_0cd325b0_uniq` (`group_id`,`permission_id`),
    ADD KEY `auth_group_permissio_permission_id_84c5c92e_fk_auth_perm` (`permission_id`);

ALTER TABLE `auth_permission`
    DROP FOREIGN KEY `content_type_id_refs_id_728de91f`,  /* `content_type_id` */
    DROP KEY `content_type_id`,  /* (`content_type_id`,`codename`) */
    DROP KEY `auth_permission_content_type_id`;
ALTER TABLE `auth_permission`
    ADD UNIQUE KEY `auth_permission_content_type_id_codename_01ab375a_uniq` (`content_type_id`,`codename`),
    ADD CONSTRAINT `auth_permission_content_type_id_2f476e4b_fk_django_co` FOREIGN KEY (`content_type_id`) REFERENCES `django_content_type` (`id`);

ALTER TABLE `blogposts`
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    MODIFY `title` varchar(255) NOT NULL,
    MODIFY `date_posted` date NOT NULL,
    MODIFY `permalink` varchar(255) NOT NULL;

ALTER TABLE `cannedresponses`
    MODIFY `id` int(10) unsigned NOT NULL,
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    MODIFY `name` varchar(255) NOT NULL,
    MODIFY `response` longtext NOT NULL,
    MODIFY `sort_group` varchar(255) NOT NULL,
    MODIFY `category` int(10) unsigned NOT NULL,
    ADD KEY `cannedresponses_type_8f3c32fc` (`type`);

ALTER TABLE `categories`
    MODIFY `id` int(10) unsigned NOT NULL,
    MODIFY `addontype_id` int(10) unsigned NOT NULL,
    MODIFY `application_id` int(10) unsigned DEFAULT NULL,
    MODIFY `weight` int(11) NOT NULL,
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    MODIFY `count` int(11) NOT NULL,
    MODIFY `slug` varchar(50) NOT NULL,
    MODIFY `misc` tinyint(1) NOT NULL,
    DROP KEY `addontype_id`,
    DROP KEY `application_id`,
    DROP KEY `categories_slug`;
ALTER TABLE `categories`
    ADD KEY `categories_slug_9bedfe6b` (`slug`);

ALTER TABLE `config`
    MODIFY `key` varchar(255) NOT NULL;
