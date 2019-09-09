ALTER TABLE `log_activity_group`
    MODIFY `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    MODIFY `group_id` int(10) unsigned NOT NULL,
    DROP KEY `group_id_refs_id_757b3ceb`,  /* (`group_id`),*/
    DROP FOREIGN KEY `group_id_refs_id_757b3ceb`,  /* (`group_id`) REFERENCES `groups` (`id`) ON DELETE CASCADE*/
    DROP KEY `activity_log_id_refs_id_15e06f3d`,  /* (`activity_log_id`),*/
    DROP FOREIGN KEY `activity_log_id_refs_id_15e06f3d`,  /* (`activity_log_id`) REFERENCES `log_activity` (`id`) ON DELETE CASCADE,*/
    ADD KEY `log_activity_group_group_id_e03ab8c8_fk_groups_id` (`group_id`),
    ADD CONSTRAINT `log_activity_group_group_id_e03ab8c8_fk_groups_id` FOREIGN KEY (`group_id`) REFERENCES `groups` (`id`),
    ADD KEY `log_activity_group_activity_log_id_e38f128d_fk_log_activity_id` (`activity_log_id`),
    ADD CONSTRAINT `log_activity_group_activity_log_id_e38f128d_fk_log_activity_id` FOREIGN KEY (`activity_log_id`) REFERENCES `log_activity` (`id`);
