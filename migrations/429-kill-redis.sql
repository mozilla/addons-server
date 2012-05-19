CREATE TABLE `compat_totals` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `app` integer UNSIGNED NOT NULL,
    `total` integer UNSIGNED NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

CREATE TABLE `fake_email` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `message` text NOT NULL,
    `created` datetime NOT NULL default '0000-00-00 00:00:00',
    `modified` datetime NOT NULL default '0000-00-00 00:00:00',
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

CREATE TABLE `paypal_checkstatus` (
    `id` int(11) AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `addon_id` int(11) NOT NULL,
    `failure_data` longtext
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `paypal_checkstatus` ADD CONSTRAINT `addon_id_refs_id_9c8e9c2` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
CREATE INDEX `paypal_checkstatus_cc3d5937` ON `paypal_checkstatus` (`addon_id`);
