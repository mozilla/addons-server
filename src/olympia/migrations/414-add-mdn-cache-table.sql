CREATE TABLE `mdn_cache` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `name` varchar(255) NOT NULL,
    `title` varchar(255) NOT NULL,
    `toc` longtext NOT NULL,
    `content` longtext NOT NULL,
    `permalink` varchar(255) NOT NULL,
    `locale` varchar(10) NOT NULL,
    UNIQUE (`name`, `locale`)
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;
