CREATE TABLE `scanners_results` (
    `id` int(11) NOT NULL AUTO_INCREMENT,
    `created` datetime(6) NOT NULL,
    `modified` datetime(6) NOT NULL,
    `upload_id` int(11) DEFAULT NULL,
    `results` longtext NOT NULL,
    `scanner` smallint(5) unsigned NOT NULL,
    `version_id` int(10) unsigned DEFAULT NULL,

    PRIMARY KEY (`id`),

    UNIQUE KEY `upload_id` (`upload_id`),
    UNIQUE KEY `version_id` (`version_id`),

    CONSTRAINT `scanners_results_upload_id_9259a7bf_fk_file_uploads_id` FOREIGN KEY (`upload_id`) REFERENCES `file_uploads` (`id`),
    CONSTRAINT `scanners_results_version_id_dd07be31_fk_versions_id` FOREIGN KEY (`version_id`) REFERENCES `versions` (`id`)
);
