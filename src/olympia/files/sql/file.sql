ALTER TABLE `files` DROP FOREIGN KEY `version_id_refs_id_e75e6066`;
ALTER TABLE `files` ADD CONSTRAINT `version_id_refs_id_e75e6066` FOREIGN KEY (`version_id`) REFERENCES `versions` (`id`) ON DELETE CASCADE;
