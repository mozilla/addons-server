ALTER TABLE `addons_categories` DROP FOREIGN KEY `addon_id_refs_id_206fde31`;
ALTER TABLE `addons_categories` ADD CONSTRAINT `addon_id_refs_id_206fde31` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`) ON DELETE CASCADE;
