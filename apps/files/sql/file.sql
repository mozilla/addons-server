ALTER TABLE `files` DROP FOREIGN KEY `version_id_refs_id_be9125ee`;
ALTER TABLE `files` ADD CONSTRAINT `version_id_refs_id_be9125ee` FOREIGN KEY (`version_id`) REFERENCES `versions` (`id`) ON DELETE CASCADE;
