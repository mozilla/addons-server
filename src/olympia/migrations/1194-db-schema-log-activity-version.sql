ALTER TABLE `log_activity_version`
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    MODIFY `version_id` int(10) unsigned NOT NULL,
    DROP KEY `activity_log_id`,
    DROP KEY `version_id`,
    DROP FOREIGN KEY `log_activity_version_ibfk_1`,  /* (`activity_log_id`) REFERENCES `log_activity` (`id`),*/
    DROP FOREIGN KEY `log_activity_version_ibfk_2`,  /* (`version_id`) REFERENCES `versions` (`id`)*/
    ADD KEY `log_activity_version_activity_log_id_e0f9b212_fk_log_activity_id` (`activity_log_id`),
    ADD KEY `log_activity_version_version_id_5280da53_fk_versions_id` (`version_id`),
    ADD CONSTRAINT `log_activity_version_activity_log_id_e0f9b212_fk_log_activity_id` FOREIGN KEY (`activity_log_id`) REFERENCES `log_activity` (`id`),
    ADD CONSTRAINT `log_activity_version_version_id_5280da53_fk_versions_id` FOREIGN KEY (`version_id`) REFERENCES `versions` (`id`);
