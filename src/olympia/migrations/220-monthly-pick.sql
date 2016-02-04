CREATE TABLE `monthly_pick` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `addon_id` int(11) unsigned NOT NULL,
    `blurb` longtext NOT NULL,
    `image` varchar(200) NOT NULL,
    `locale` varchar(30) NOT NULL UNIQUE
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `monthly_pick` ADD CONSTRAINT `addon_id_refs_id_a94677f3` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
CREATE INDEX `monthly_pick_cc3d5937` ON `monthly_pick` (`addon_id`);
