CREATE TABLE `bluevia` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `user_id` int(11) unsigned NOT NULL,
    `developer_id` varchar(64) NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;
ALTER TABLE `bluevia` ADD CONSTRAINT `user_id_refs_id_99d7c3ef` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

CREATE TABLE `addon_bluevia` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `addon_id` int(11) unsigned NOT NULL UNIQUE,
    `bluevia_config_id` int(11) unsigned NOT NULL,
    `status` int(11) unsigned NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `addon_bluevia` ADD CONSTRAINT `addon_id_refs_id_5ed7b414` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
ALTER TABLE `addon_bluevia` ADD CONSTRAINT `bluevia_config_id_refs_id_ef26bb4` FOREIGN KEY (`bluevia_config_id`) REFERENCES `bluevia` (`id`);
CREATE INDEX `bluevia_fbfc09f1` ON `bluevia` (`user_id`);
CREATE INDEX `bluevia_dev_id_index` ON `bluevia` (`developer_id`);
CREATE INDEX `addon_bluevia_a27b43ff` ON `addon_bluevia` (`bluevia_config_id`);
CREATE INDEX `addon_bluevia_c9ad71dd` ON `addon_bluevia` (`status`);


INSERT INTO `waffle_switch_mkt` (name, active, note)
    VALUES ('enabled-paypal', 0, 'Enable this to enable PayPal payments in '
                                 'Developer Hub (and soon in consumer pages).');

INSERT INTO `waffle_switch_mkt` (name, active, note)
    VALUES ('enabled-bluevia', 0, 'Enable this to enable BlueVia payments in '
                                  'Developer Hub (and soon in consumer pages).');
