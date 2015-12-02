CREATE TABLE `incompatible_versions` (
    `id` int(11) UNSIGNED AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `version_id` int(11) UNSIGNED NOT NULL,
    `app_id` int(11) UNSIGNED NOT NULL,
    `min_app_version` varchar(255) NOT NULL,
    `max_app_version` varchar(255) NOT NULL,
    `min_app_version_int` bigint,
    `max_app_version_int` bigint
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `incompatible_versions` ADD FOREIGN KEY (`app_id`) REFERENCES `applications` (`id`);
ALTER TABLE `incompatible_versions` ADD FOREIGN KEY (`version_id`) REFERENCES `versions` (`id`);

CREATE INDEX `incompatible_versions_fef0b09d` ON `incompatible_versions` (`version_id`);
CREATE INDEX `incompatible_versions_269da59a` ON `incompatible_versions` (`app_id`);
CREATE INDEX `incompatible_versions_68156cb3` ON `incompatible_versions` (`min_app_version_int`);
CREATE INDEX `incompatible_versions_3d2f16b5` ON `incompatible_versions` (`max_app_version_int`);
