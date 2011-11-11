ALTER TABLE `appsupport` DROP FOREIGN KEY `addon_id_refs_id_fd65824a`;
ALTER TABLE `appsupport` ADD CONSTRAINT `addon_id_refs_id_fd65824a` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`) ON DELETE CASCADE;
