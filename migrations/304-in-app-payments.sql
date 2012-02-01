CREATE TABLE `addon_inapp` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `addon_id` int(11) unsigned NOT NULL,
    `chargeback_url` varchar(200) NOT NULL,
    `postback_url` varchar(200) NOT NULL,
    `private_key` varchar(255) NOT NULL UNIQUE,
    `public_key` varchar(255) NOT NULL UNIQUE,
    `status` int(11) unsigned NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `addon_inapp` ADD CONSTRAINT `addon_id_addon` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
CREATE INDEX `addon_inapp_app` ON `addon_inapp` (`addon_id`);
CREATE INDEX `addon_inapp_status` ON `addon_inapp` (`status`);
CREATE INDEX `addon_inapp_public_key` ON `addon_inapp` (`public_key`);
