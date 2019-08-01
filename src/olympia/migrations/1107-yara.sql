CREATE TABLE `yara_results` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime(6) NOT NULL,
    `modified` datetime(6) NOT NULL,
    `upload_id` int(11),
    `version_id` integer unsigned,
    `matches` longtext,

    FOREIGN KEY (`upload_id`) REFERENCES `file_uploads` (`id`) ON DELETE SET NULL,
    FOREIGN KEY (`version_id`) REFERENCES `versions` (`id`)
);
