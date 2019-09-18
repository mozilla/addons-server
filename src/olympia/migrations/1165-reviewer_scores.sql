ALTER TABLE `reviewer_scores`
    DROP FOREIGN KEY `reviewer_scores_addon_id_fk`,
    DROP FOREIGN KEY `reviewer_scores_user_id_fk`,
    CHANGE COLUMN `id` `id` INT (10) UNSIGNED NOT NULL AUTO_INCREMENT,
    CHANGE COLUMN `addon_id` `addon_id` INT (10) UNSIGNED DEFAULT NULL,
    CHANGE COLUMN `created` `created` DATETIME (6) NOT NULL,
    CHANGE COLUMN `modified` `modified` DATETIME (6) NOT NULL,
    CHANGE COLUMN `note_key` `note_key` SMALLINT (6) NOT NULL,
    ADD CONSTRAINT `reviewer_scores_user_id_930c6267_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
    ADD CONSTRAINT `reviewer_scores_version_id_0b46ae70_fk_versions_id` FOREIGN KEY (`version_id`) REFERENCES `versions` (`id`),
    ADD CONSTRAINT `reviewer_scores_addon_id_ccc7c6e4_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
