ALTER TABLE `previews` DROP FOREIGN KEY `previews_ibfk_1`;
ALTER TABLE `previews` ADD CONSTRAINT `previews_ibfk_1` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`) ON DELETE CASCADE;
