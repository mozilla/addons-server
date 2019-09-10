ALTER TABLE `webext_permissions`
    DROP FOREIGN KEY `webext_permissions_file`,
    CHANGE COLUMN `created` `created` DATETIME (6) NOT NULL,
    CHANGE COLUMN `modified` `modified` DATETIME (6) NOT NULL,
    CHANGE COLUMN `permissions` `permissions` LONGTEXT NOT NULL,
    CHANGE COLUMN `file_id` `file_id` INT (10) UNSIGNED NOT NULL,
    ADD INDEX `webext_permissions_file_id_a54af0b1_fk_files_id` (`file_id`),
    ADD CONSTRAINT `webext_permissions_file_id_a54af0b1_fk_files_id` FOREIGN KEY (`file_id`) REFERENCES `files` (`id`);
