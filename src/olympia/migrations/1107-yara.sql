CREATE TABLE `yara_results` (
    `id` int(11) AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime(6) NOT NULL,
    `modified` datetime(6) NOT NULL,
    `upload_id` int(11) DEFAULT NULL,
    `version_id` int(10) unsigned DEFAULT NULL,
    `matches` longtext NOT NULL,

    UNIQUE KEY `upload_id` (`upload_id`),
    UNIQUE KEY `version_id` (`version_id`),

    CONSTRAINT `yara_results_upload_id_5cf355f9_fk_file_uploads_id` FOREIGN KEY (`upload_id`) REFERENCES `file_uploads` (`id`) ON DELETE SET NULL,
    CONSTRAINT `yara_results_version_id_b32a0f70_fk_versions_id` FOREIGN KEY (`version_id`) REFERENCES `versions` (`id`) ON DELETE CASCADE
);
