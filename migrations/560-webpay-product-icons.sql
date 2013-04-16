CREATE TABLE `payment_assets` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `ext_url` varchar(255) NOT NULL,
    `ext_size` int(11) unsigned NOT NULL,
    `size` int(11) unsigned NOT NULL,
    `format` varchar(4) NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

CREATE INDEX `payment_assets_3d23e06b` ON `payment_assets` (`ext_url`);
CREATE INDEX `payment_assets_a6ff5cf0` ON `payment_assets` (`size`);
