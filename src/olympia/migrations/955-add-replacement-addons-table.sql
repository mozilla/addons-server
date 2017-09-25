DROP TABLE IF EXISTS `replacement_addons`;

CREATE TABLE `replacement_addons`(
    `id` int(11) AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `guid` CHAR(255) UNIQUE NULL,
    `path` CHAR(255) NULL
) DEFAULT CHARSET=utf8;
