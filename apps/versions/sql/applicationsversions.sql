ALTER TABLE `applications_versions` DROP FOREIGN KEY `version_id_refs_id_284c630`;
ALTER TABLE `applications_versions` ADD CONSTRAINT `version_id_refs_id_284c630` FOREIGN KEY (`version_id`) REFERENCES `versions` (`id`) ON DELETE CASCADE;
