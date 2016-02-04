CREATE TABLE `flags` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `addon_id` int(11) unsigned NOT NULL UNIQUE,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `adult_content` int(1) unsigned NOT NULL DEFAULT '0',
    `child_content` int(1) unsigned NOT NULL DEFAULT '0'
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `flags` ADD CONSTRAINT `addon_id_refs_id_12bf23e` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);

CREATE INDEX `flags_2c4ada64` ON `flags` (`adult_content`);
CREATE INDEX `flags_5462cd52` ON `flags` (`child_content`);
