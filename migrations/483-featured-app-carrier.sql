CREATE TABLE `zadmin_featuredappcarrier` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `featured_app_id` int(11) unsigned NOT NULL,
    `carrier` varchar(255) NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;
