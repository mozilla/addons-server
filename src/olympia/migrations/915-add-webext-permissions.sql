CREATE TABLE `webext_permissions` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `name` char(255) NOT NULL UNIQUE,
    `enum` integer unsigned
) DEFAULT CHARSET=utf8;

CREATE TABLE `file_webext_permissions` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `file_id` int(11) NOT NULL,
    `permission_id` int(11) unsigned NOT NULL
) DEFAULT CHARSET=utf8;

ALTER TABLE `file_webext_permissions` ADD CONSTRAINT `file_webext_permissions_file`
    FOREIGN KEY (`file_id`) REFERENCES `files` (`id`);
ALTER TABLE `file_webext_permissions` ADD CONSTRAINT `file_webext_permissions_permission`
    FOREIGN KEY (`permission_id`) REFERENCES `webext_permissions` (`id`);
