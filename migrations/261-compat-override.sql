CREATE TABLE `compat_override` (
    `id` int(11) UNSIGNED NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `name` varchar(255),
    `guid` varchar(255) NOT NULL UNIQUE,
    `addon_id` int(11) UNSIGNED
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;
ALTER TABLE `compat_override`
    ADD CONSTRAINT FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);

CREATE TABLE `compat_override_range` (
    `id` int(11) UNSIGNED NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `compat_id` int(11) UNSIGNED NOT NULL,
    `type` smallint NOT NULL,
    `min_version` varchar(255) NOT NULL,
    `max_version` varchar(255) NOT NULL,
    `app_id` int(11) UNSIGNED NOT NULL,
    `min_app_version` varchar(255) NOT NULL,
    `max_app_version` varchar(255) NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;
ALTER TABLE `compat_override_range`
    ADD CONSTRAINT FOREIGN KEY (`app_id`) REFERENCES `applications` (`id`);
ALTER TABLE `compat_override_range`
    ADD CONSTRAINT FOREIGN KEY (`compat_id`) REFERENCES `compat_override` (`id`);
