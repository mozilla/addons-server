ALTER TABLE `versions` DROP FOREIGN KEY `addon_id_refs_id_8420fd09`;
ALTER TABLE `versions` ADD CONSTRAINT `addon_id_refs_id_8420fd09` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`) ON DELETE CASCADE;
