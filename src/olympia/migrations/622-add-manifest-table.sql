CREATE TABLE `app_manifest` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `version_id` int(11) unsigned NOT NULL UNIQUE,
    `manifest` longtext NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `app_manifest` ADD CONSTRAINT `app_manifest_version_id`
    FOREIGN KEY (`version_id`) REFERENCES `versions` (`id`) ON DELETE CASCADE;
