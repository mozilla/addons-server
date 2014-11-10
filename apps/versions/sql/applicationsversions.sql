ALTER TABLE `applications_versions` DROP FOREIGN KEY `version_id_refs_id_b835e94d`;
ALTER TABLE `applications_versions` ADD CONSTRAINT `version_id_refs_id_b835e94d` FOREIGN KEY (`version_id`) REFERENCES `versions` (`id`) ON DELETE CASCADE;
