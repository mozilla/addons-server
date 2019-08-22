ALTER TABLE `scanners_results` DROP FOREIGN KEY `scanners_results_upload_id_9259a7bf_fk_file_uploads_id`;
ALTER TABLE `scanners_results` DROP FOREIGN KEY `scanners_results_version_id_dd07be31_fk_versions_id`;
ALTER TABLE `scanners_results` DROP INDEX `upload_id`;
ALTER TABLE `scanners_results` DROP INDEX `version_id`;
ALTER TABLE `scanners_results` ADD CONSTRAINT `scanners_results_upload_id_scanner_version_id_ad9eb8a6_uniq` UNIQUE (`upload_id`,`scanner`,`version_id`);
ALTER TABLE `scanners_results` ADD KEY `scanners_results_version_id_dd07be31_fk_versions_id` (`version_id`);
ALTER TABLE `scanners_results` ADD CONSTRAINT `scanners_results_upload_id_9259a7bf_fk_file_uploads_id` FOREIGN KEY (`upload_id`) REFERENCES `file_uploads` (`id`);
ALTER TABLE `scanners_results` ADD CONSTRAINT `scanners_results_version_id_dd07be31_fk_versions_id` FOREIGN KEY (`version_id`) REFERENCES `versions` (`id`);
