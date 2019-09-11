ALTER TABLE `file_validation`
    MODIFY `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    MODIFY `file_id` int(10) unsigned NOT NULL;
ALTER TABLE `file_validation`
    ADD CONSTRAINT `file_validation_file_id_48b46a5a_fk_files_id` FOREIGN KEY (`file_id`) REFERENCES `files` (`id`);
