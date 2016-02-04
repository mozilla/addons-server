CREATE TABLE `addon_inapp_payment` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `config_id` int(11) unsigned NOT NULL,
    `contribution_id` int(11) unsigned NOT NULL,
    `name` varchar(100) NOT NULL,
    `description` varchar(255) NOT NULL,
    `app_data` varchar(255) NOT NULL,
    UNIQUE (`config_id`, `contribution_id`)
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `addon_inapp_payment` ADD CONSTRAINT `config_id_refs_id_7c502d8c` FOREIGN KEY (`config_id`) REFERENCES `addon_inapp` (`id`);
ALTER TABLE `addon_inapp_payment` ADD CONSTRAINT `contribution_id_refs_id_5d086f0` FOREIGN KEY (`contribution_id`) REFERENCES `stats_contributions` (`id`);
CREATE INDEX `addon_inapp_payment_c41bdac` ON `addon_inapp_payment` (`config_id`);
CREATE INDEX `addon_inapp_payment_1b9d2c16` ON `addon_inapp_payment` (`contribution_id`);


CREATE TABLE `addon_inapp_notice` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `notice` int(11) unsigned NOT NULL,
    `url` varchar(255) NOT NULL,
    `payment_id` int(11) unsigned NOT NULL,
    `success` bool NOT NULL,
    `last_error` varchar(255)
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `addon_inapp_notice` ADD CONSTRAINT `payment_id_refs_id_8a79c182` FOREIGN KEY (`payment_id`) REFERENCES `addon_inapp_payment` (`id`);
CREATE INDEX `addon_inapp_notice_842c533d` ON `addon_inapp_notice` (`payment_id`);
