CREATE TABLE `image_assets` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `addon_id` int(11) unsigned NOT NULL,
    `filetype` varchar(25) NOT NULL,
    `slug` varchar(25) NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `image_assets` ADD CONSTRAINT `addon_id_refs_id_5ef1767b` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);

CREATE INDEX `imageassets_ab59e4f` on `image_assets` (`addon_id`, `slug`);
