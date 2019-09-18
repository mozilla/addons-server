ALTER TABLE `django_admin_log`
    MODIFY `action_time` datetime(6) NOT NULL,
    DROP KEY `django_admin_log_user_id`,  /* (`user_id`),*/
    DROP KEY `django_admin_log_content_type_id`,  /* (`content_type_id`),*/
    DROP FOREIGN KEY `content_type_id_refs_id_288599e6`,  /* (`content_type_id`) REFERENCES `django_content_type` (`id`),*/
    DROP FOREIGN KEY `user_id_refs_id_c8665aa`,  /* (`user_id`) REFERENCES `users` (`id`),*/
    ADD CONSTRAINT `django_admin_log_content_type_id_c4bce8eb_fk_django_co` FOREIGN KEY (`content_type_id`) REFERENCES `django_content_type` (`id`),
    ADD CONSTRAINT `django_admin_log_user_id_c564eba6_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

ALTER TABLE `django_content_type`
    DROP KEY `app_label`,  /* (`app_label`,`model`),*/
    ADD UNIQUE KEY `django_content_type_app_label_model_76bd3d3b_uniq` (`app_label`,`model`);

ALTER TABLE `django_session`
    MODIFY `expire_date` datetime(6) NOT NULL,
    ADD KEY `django_session_expire_date_a5c62663` (`expire_date`);
