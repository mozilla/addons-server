CREATE TABLE `addons_blacklistedslug` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `name` varchar(255) NOT NULL UNIQUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8
;
INSERT INTO `addons_blacklistedslug` VALUE(1, NOW(), NOW(), "validate");
INSERT INTO `addons_blacklistedslug` VALUE(2, NOW(), NOW(), "submit");
