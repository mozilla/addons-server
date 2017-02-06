ALTER TABLE `webext_permissions` DROP FOREIGN KEY `webext_permissions_file`;

-- This will fail locally as file.id is by default signed, but unsigned on prod, etc.
ALTER TABLE `webext_permissions` MODIFY `file_id` int(11) unsigned UNIQUE NOT NULL;

ALTER TABLE `webext_permissions` ADD CONSTRAINT `webext_permissions_file`
    FOREIGN KEY (`file_id`) REFERENCES `files` (`id`);