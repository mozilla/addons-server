ALTER TABLE `appsupport` DROP FOREIGN KEY `addon_id_refs_id_c3c65b00`;
ALTER TABLE `appsupport` ADD CONSTRAINT `addon_id_refs_id_c3c65b00` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`) ON DELETE CASCADE;
