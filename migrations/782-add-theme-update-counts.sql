CREATE TABLE `theme_update_counts` (
    `id` int(11) UNSIGNED AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `addon_id` int(11) UNSIGNED NOT NULL DEFAULT '0',
    `count` int(11) UNSIGNED NOT NULL DEFAULT '0',
    `date` date NOT NULL DEFAULT '0000-00-00'
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;
ALTER TABLE `theme_update_counts` ADD CONSTRAINT `theme_update_counts_addon_id_key` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
CREATE INDEX `theme_update_counts_addon_id_index` ON `theme_update_counts` (`addon_id`);
CREATE INDEX `theme_update_counts_count_index` ON `theme_update_counts` (`count`);
CREATE INDEX `theme_update_counts_date_index` ON `theme_update_counts` (`date`);
CREATE INDEX `theme_update_counts_addon_id_count_index` ON `theme_update_counts` (`addon_id`,`count`);
