ALTER TABLE theme_user_counts
    CHANGE COLUMN `addon_id` `addon_id` int(11) UNSIGNED NOT NULL,
    ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;
