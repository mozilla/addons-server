ALTER TABLE `applications_versions`
    MODIFY `application_id` int(10) unsigned NOT NULL,
    MODIFY `version_id` int(10) unsigned NOT NULL,
    MODIFY `min` int(10) unsigned NOT NULL,
    MODIFY `max` int(10) unsigned NOT NULL,
    DROP FOREIGN KEY `applications_versions_ibfk_4`,  /* `version_id` */
    DROP FOREIGN KEY `applications_versions_ibfk_5`,  /* `min` */
    DROP FOREIGN KEY `applications_versions_ibfk_6`,  /* `max` */
    ADD CONSTRAINT `applications_versions_version_id_9bf048e6_fk_versions_id` FOREIGN KEY (`version_id`) REFERENCES `versions` (`id`),
    ADD CONSTRAINT `applications_versions_min_1c31b27c_fk_appversions_id` FOREIGN KEY (`min`) REFERENCES `appversions` (`id`),
    ADD CONSTRAINT `applications_versions_max_6e57db5a_fk_appversions_id` FOREIGN KEY (`max`) REFERENCES `appversions` (`id`);
