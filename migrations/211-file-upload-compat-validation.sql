ALTER TABLE file_uploads
    ADD COLUMN `compat_with_app_id` int(11) unsigned NULL;
ALTER TABLE file_uploads
    ADD COLUMN `compat_with_appver_id` int(11) unsigned NULL;

ALTER TABLE `file_uploads`
    ADD CONSTRAINT `compat_with_app_id_refs_id_939661ad`
    FOREIGN KEY (`compat_with_app_id`) REFERENCES `applications` (`id`);
ALTER TABLE `file_uploads`
    ADD CONSTRAINT `compat_with_appver_id_refs_id_3747a309`
    FOREIGN KEY (`compat_with_appver_id`) REFERENCES `appversions` (`id`);

CREATE INDEX `file_uploads_afe99c5e` ON `file_uploads` (`compat_with_app_id`);
CREATE INDEX `file_uploads_9a93262a` ON `file_uploads` (`compat_with_appver_id`);
