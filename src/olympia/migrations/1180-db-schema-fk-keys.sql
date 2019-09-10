ALTER TABLE `abuse_reports`
    DROP KEY `reporter_id_refs_id_12d88e23`,  /*(`reporter_id`),*/
    DROP KEY `user_id_refs_id_12d88e23`,  /* (`user_id`),*/
    DROP KEY `addon_id_refs_id_2b6ff2a7`,  /* (`addon_id`);*/
    ADD KEY `abuse_reports_reporter_id_e5b6b72a_fk_users_id` (`reporter_id`),
    ADD KEY `abuse_reports_addon_id_f15faa13_fk_addons_id` (`addon_id`),
    ADD KEY `abuse_reports_user_id_67401662_fk_users_id` (`user_id`);

ALTER TABLE `addons`
    DROP KEY `addons_ibfk_3`,  /* (`homepage`),*/
    DROP KEY `addons_ibfk_4`,  /* (`description`),*/
    DROP KEY `addons_ibfk_5`,  /* (`summary`),*/
    DROP KEY `addons_ibfk_6`,  /* (`developercomments`),*/
    DROP KEY `addons_ibfk_7`,  /* (`eula`),*/
    DROP KEY `addons_ibfk_8`;  /* (`privacypolicy`),*/

ALTER TABLE `addons_users`
    DROP KEY `user_id`,  /* (`user_id`),*/
    ADD KEY `addons_users_user_id_411d394c` (`user_id`);

ALTER TABLE `addons_users_pending_confirmation`
    DROP KEY `addons_users_pending_confirmation_user_id_a9a86f72_fk_users_id`,  /* (`user_id`),*/
    ADD KEY `addons_users_pending_confirmation_user_id_a9a86f72` (`user_id`);

ALTER TABLE `akismet_reports`
    DROP KEY `akismet_reports_addon_instance_id_fk_addons_id`,  /* (`addon_instance_id`),*/
    DROP KEY `akismet_reports_upload_instance_id_fk_file_uploads_id`,  /* (`upload_instance_id`),*/
    DROP KEY `akismet_reports_collection_instance_id_fk_collections_id`,  /* (`collection_instance_id`),*/
    DROP KEY `akismet_reports_user_id_fk_users_id`,  /* (`user_id`),*/
    ADD KEY `akismet_reports_addon_instance_id_03f471af_fk_addons_id` (`addon_instance_id`),
    ADD KEY `akismet_reports_upload_instance_id_c4530dc1_fk_file_uploads_id` (`upload_instance_id`),
    ADD KEY `akismet_reports_collection_instance__2c06adf6_fk_collectio` (`collection_instance_id`),
    ADD KEY `akismet_reports_user_id_97ce80b4_fk_users_id` (`user_id`);

ALTER TABLE `applications_versions`
    DROP KEY `version_id`,
    DROP KEY `min`,
    DROP KEY `max`,
    ADD KEY `applications_versions_version_id_9bf048e6_fk_versions_id` (`version_id`),
    ADD KEY `applications_versions_min_1c31b27c_fk_appversions_id` (`min`),
    ADD KEY `applications_versions_max_6e57db5a_fk_appversions_id` (`max`);
