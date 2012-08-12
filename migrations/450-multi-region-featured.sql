ALTER TABLE zadmin_featuredapp DROP COLUMN region;
CREATE TABLE `zadmin_featuredappregion` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `featured_app_id` int(11) unsigned NOT NULL,
    `region` tinyint(2) UNSIGNED NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;
