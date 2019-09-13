ALTER TABLE `waffle_flag`
    MODIFY `note` longtext NOT NULL,
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    ADD KEY `waffle_flag_created_4a6e8cef` (`created`);

ALTER TABLE `waffle_flag_groups`
    DROP KEY `flag_id`,  /* UNIQUE (`flag_id`,`group_id`),*/
    DROP KEY `group_id_refs_id_4ea49f34`,  /* (`group_id`),*/
    ADD UNIQUE KEY `waffle_flag_groups_flag_id_group_id_8ba0c71b_uniq` (`flag_id`,`group_id`),
    ADD KEY `waffle_flag_groups_group_id_a97c4f66_fk_auth_group_id` (`group_id`);

ALTER TABLE `waffle_flag_users`
    DROP KEY `flag_id`,  /* UNIQUE (`flag_id`,`userprofile_id`),*/
    DROP KEY `user_id_refs_id_bae2dfc2`,  /* (`userprofile_id`),*/
    ADD UNIQUE KEY `waffle_flag_users_flag_id_userprofile_id_09cba513_uniq` (`flag_id`,`userprofile_id`),
    ADD KEY `waffle_flag_users_userprofile_id_28cfad9f_fk_users_id` (`userprofile_id`);

ALTER TABLE `waffle_sample`
    MODIFY `note` longtext NOT NULL,
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    ADD KEY `waffle_sample_created_76198bd5` (`created`);

ALTER TABLE `waffle_switch`
    MODIFY `note` longtext NOT NULL,
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    ADD KEY `waffle_switch_created_c004e77e` (`created`);
