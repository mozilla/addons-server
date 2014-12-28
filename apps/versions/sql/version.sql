ALTER TABLE `versions` DROP FOREIGN KEY `addon_id_refs_id_0b364cd2`;
ALTER TABLE `versions` ADD CONSTRAINT `addon_id_refs_id_0b364cd2` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`) ON DELETE CASCADE;
