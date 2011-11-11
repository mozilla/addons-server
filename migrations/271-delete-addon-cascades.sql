ALTER TABLE `addons_categories` DROP FOREIGN KEY `addons_categories_ibfk_3`;
ALTER TABLE `addons_categories` ADD CONSTRAINT `addons_categories_ibfk_3` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`) ON DELETE CASCADE;
ALTER TABLE `addons_users` DROP FOREIGN KEY `addons_users_ibfk_1`;
ALTER TABLE `addons_users` ADD CONSTRAINT `addons_users_ibfk_1` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`) ON DELETE CASCADE;
-- Table `appsupport` doesn't have a FK constraint on server currently. The below may fail, which is ok.
ALTER TABLE `appsupport` DROP FOREIGN KEY `addon_id_refs_id_fd65824a`;
ALTER TABLE `appsupport` ADD CONSTRAINT `addon_id_refs_id_fd65824a` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`) ON DELETE CASCADE;
ALTER TABLE `submit_step` DROP FOREIGN KEY `submit_step_ibfk_1`;
ALTER TABLE `submit_step` ADD CONSTRAINT `submit_step_ibfk_1` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`) ON DELETE CASCADE;
ALTER TABLE `files` DROP FOREIGN KEY `files_ibfk_1`;
ALTER TABLE `files` ADD CONSTRAINT `files_ibfk_1` FOREIGN KEY (`version_id`) REFERENCES `versions` (`id`) ON DELETE CASCADE;
ALTER TABLE `applications_versions` DROP FOREIGN KEY `applications_versions_ibfk_4`;
ALTER TABLE `applications_versions` ADD CONSTRAINT `applications_versions_ibfk_4` FOREIGN KEY (`version_id`) REFERENCES `versions` (`id`) ON DELETE CASCADE;
ALTER TABLE `versions` DROP FOREIGN KEY `versions_ibfk_1`;
ALTER TABLE `versions` ADD CONSTRAINT `versions_ibfk_1` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`) ON DELETE CASCADE;
