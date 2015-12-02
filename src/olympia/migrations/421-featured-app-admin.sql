CREATE TABLE `zadmin_featuredapp` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `app_id` integer NOT NULL,
    `category_id` int(11) unsigned,
    `is_sponsor` bool NOT NULL,
    FOREIGN KEY (`category_id`) REFERENCES `categories` (`id`)
    ) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;
