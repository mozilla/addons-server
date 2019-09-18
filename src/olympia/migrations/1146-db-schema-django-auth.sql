ALTER TABLE `auth_group`
    MODIFY `name` varchar(150) NOT NULL;

ALTER TABLE `auth_group_permissions`
    DROP FOREIGN KEY `group_id_refs_id_3cea63fe`,  /* `group_id` */
    DROP FOREIGN KEY `permission_id_refs_id_5886d21f`,  /* `permission_id` */
    DROP KEY `group_id`,  /* (`group_id`,`permission_id`), */
    DROP KEY `auth_group_permissions_group_id`,
    DROP KEY `auth_group_permissions_permission_id`,
    ADD CONSTRAINT `auth_group_permissions_group_id_b120cbf9_fk_auth_group_id` FOREIGN KEY (`group_id`) REFERENCES `auth_group` (`id`),
    ADD CONSTRAINT `auth_group_permissio_permission_id_84c5c92e_fk_auth_perm` FOREIGN KEY (`permission_id`) REFERENCES `auth_permission` (`id`),
    ADD UNIQUE KEY `auth_group_permissions_group_id_permission_id_0cd325b0_uniq` (`group_id`,`permission_id`),
    ADD KEY `auth_group_permissio_permission_id_84c5c92e_fk_auth_perm` (`permission_id`);

ALTER TABLE `auth_permission`
    DROP FOREIGN KEY `content_type_id_refs_id_728de91f`,  /* `content_type_id` */
    DROP KEY `content_type_id`,  /* (`content_type_id`,`codename`) */
    DROP KEY `auth_permission_content_type_id`,
    ADD UNIQUE KEY `auth_permission_content_type_id_codename_01ab375a_uniq` (`content_type_id`,`codename`),
    ADD CONSTRAINT `auth_permission_content_type_id_2f476e4b_fk_django_co` FOREIGN KEY (`content_type_id`) REFERENCES `django_content_type` (`id`);
