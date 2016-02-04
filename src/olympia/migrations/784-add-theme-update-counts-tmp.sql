CREATE TABLE `theme_update_counts_bulk` (
    `id` int(11) UNSIGNED AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `persona_id` int(11) UNSIGNED NOT NULL,
    `popularity` int(11) UNSIGNED,
    `movers` DOUBLE
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;
