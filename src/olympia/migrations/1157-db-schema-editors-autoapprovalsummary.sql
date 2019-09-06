ALTER TABLE `editors_autoapprovalsummary`
    MODIFY `has_auto_approval_disabled` tinyint(1) NOT NULL,
    MODIFY `is_recommendable` tinyint(1) NOT NULL,
    MODIFY `should_be_delayed` tinyint(1) NOT NULL,
    DROP FOREIGN KEY `version_id_refs_id_6d27bb3c`, /* (`version_id`) REFERENCES `versions` (`id`) */
    ADD CONSTRAINT `editors_autoapprovalsummary_version_id_e7bfa9f9_fk_versions_id` FOREIGN KEY (`version_id`) REFERENCES `versions` (`id`);
