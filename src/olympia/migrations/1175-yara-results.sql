-- Has to be done in 2 ALTER TABLE because we're dropping and re-adding a constraint by the same
-- name, just to remove the ON DELETE CASCADE bit.
ALTER TABLE `yara_results`
    DROP FOREIGN KEY `yara_results_upload_id_5cf355f9_fk_file_uploads_id`,
    DROP FOREIGN KEY `yara_results_version_id_b32a0f70_fk_versions_id`;
ALTER TABLE `yara_results`
    ADD CONSTRAINT `yara_results_upload_id_5cf355f9_fk_file_uploads_id` FOREIGN KEY (`upload_id`) REFERENCES `file_uploads` (`id`),
    ADD CONSTRAINT `yara_results_version_id_b32a0f70_fk_versions_id` FOREIGN KEY (`version_id`) REFERENCES `versions` (`id`);
