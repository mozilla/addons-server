CREATE TABLE `appsupport` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `addon_id` int(11) unsigned NOT NULL,
    `app_id` int(11) unsigned NOT NULL
)
;
ALTER TABLE `appsupport` ADD CONSTRAINT `addon_id_refs_id_fd65824a` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
ALTER TABLE `appsupport` ADD CONSTRAINT `app_id_refs_id_481ce338` FOREIGN KEY (`app_id`) REFERENCES `applications` (`id`);
COMMIT;
