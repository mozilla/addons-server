ALTER TABLE `addons_categories` DROP FOREIGN KEY `addon_id_refs_id_dd972ca1`;
ALTER TABLE `addons_categories` ADD CONSTRAINT `addon_id_refs_id_dd972ca1` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`) ON DELETE CASCADE;
