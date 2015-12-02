CREATE TABLE `prices` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `price` numeric(5, 2) NOT NULL,
    `name` int(11) unsigned DEFAULT NULL,
    `active` bool DEFAULT True NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `prices` ADD CONSTRAINT `name_translated` FOREIGN KEY (`name`) REFERENCES `translations` (`id`);
CREATE INDEX `active_idx` ON `prices` (active);
