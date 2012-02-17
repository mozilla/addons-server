CREATE TABLE `addon_payment_data` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `addon_id` int(11) unsigned NOT NULL UNIQUE,
    `first_name` varchar(255) NOT NULL,
    `last_name` varchar(255) NOT NULL,
    `email` varchar(75) NOT NULL,
    `full_name` varchar(255) NOT NULL,
    `business_name` varchar(255) NOT NULL,
    `country` varchar(64) NOT NULL,
    `payerID` varchar(255) NOT NULL,
    `date_of_birth` date,
    `address_one` varchar(255) NOT NULL,
    `address_two` varchar(255) NOT NULL,
    `post_code` varchar(128) NOT NULL,
    `state` varchar(64) NOT NULL,
    `phone` varchar(32) NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;
ALTER TABLE `addon_payment_data` ADD CONSTRAINT `addon_id_refs_id_addon` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
CREATE INDEX `addon_payment_data` ON `addon_payment_data` (`addon_id`);
