ALTER TABLE `version_previews`
    DROP FOREIGN KEY `version_previews_version_id_fk_versions_id`,
    CHANGE COLUMN `version_id` `version_id` INT (10) UNSIGNED NOT NULL,
    CHANGE COLUMN `position` `position` INT (11) NOT NULL,
    ADD INDEX `version_previews_version_id_49b254c1_fk_versions_id` (`version_id`),
    ADD CONSTRAINT `version_previews_version_id_49b254c1_fk_versions_id` FOREIGN KEY (`version_id`) REFERENCES `versions` (`id`);
