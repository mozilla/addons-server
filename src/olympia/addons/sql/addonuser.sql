ALTER TABLE `addons_users` DROP FOREIGN KEY `addon_id_refs_id_0ace0094`;
ALTER TABLE `addons_users` ADD CONSTRAINT `addon_id_refs_id_0ace0094` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`) ON DELETE CASCADE;
