CREATE TABLE `compat_totals` (
    `id` int(11) AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `app` int(11) UNSIGNED NOT NULL,
    `total` int(11) UNSIGNED NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

CREATE TABLE `fake_email` (
    `id` int(11) AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `message` text NOT NULL,
    `created` datetime NOT NULL default '0000-00-00 00:00:00',
    `modified` datetime NOT NULL default '0000-00-00 00:00:00'
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

CREATE TABLE `paypal_checkstatus` (
    `id` int(11) AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `addon_id` int(11) unsigned NOT NULL,
    `failure_data` longtext
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `paypal_checkstatus` ADD CONSTRAINT `paypal_checkstatys_addon_id_fk` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
CREATE INDEX `paypal_checkstatus_addon_id_idx` ON `paypal_checkstatus` (`addon_id`);
