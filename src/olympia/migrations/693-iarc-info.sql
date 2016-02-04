CREATE TABLE `webapps_iarc_info` (
    `id` int(11) UNSIGNED AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `addon_id` int(11) UNSIGNED NOT NULL UNIQUE,
    `submission_id` int(11) UNSIGNED NOT NULL,
    `security_code` varchar(10) NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `webapps_iarc_info` ADD CONSTRAINT `addon_id_iarc_info` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
