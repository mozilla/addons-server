ALTER TABLE `addons_premium` DROP FOREIGN KEY `addon_id_refs_id_addons_premium`;
ALTER TABLE `addons_premium` ADD CONSTRAINT `addon_id_refs_id_addons_premium`
    FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`) ON DELETE CASCADE;
