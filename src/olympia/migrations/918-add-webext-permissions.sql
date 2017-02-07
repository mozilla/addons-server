DROP TABLE IF EXISTS `webext_permissions`;

CREATE TABLE `webext_permissions` (
    `id` int(11) AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `permissions` longtext,
    `file_id` int(11) unsigned NOT NULL
) DEFAULT CHARSET=utf8;

ALTER TABLE `webext_permissions` ADD CONSTRAINT `webext_permissions_file`
    FOREIGN KEY (`file_id`) REFERENCES `files` (`id`);
