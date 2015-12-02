ALTER TABLE `submit_step` DROP FOREIGN KEY `submit_step_ibfk_1`;
ALTER TABLE `submit_step` ADD CONSTRAINT `submit_step_ibfk_1` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`) ON DELETE CASCADE;
