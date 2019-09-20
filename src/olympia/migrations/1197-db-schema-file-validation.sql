/*
-- Already executed on dev, stage and prod
ALTER TABLE `file_validation`
    MODIFY `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    MODIFY `file_id` int(10) unsigned NOT NULL;
*/

DELETE FROM `file_validation` USING `file_validation`
    LEFT JOIN `files` ON `file_id` = `files`.`id`
    WHERE `files`.`id` IS NULL AND `file_id` IS NOT NULL;

ALTER TABLE `file_validation`
    ADD CONSTRAINT `file_validation_file_id_48b46a5a_fk_files_id` FOREIGN KEY (`file_id`) REFERENCES `files` (`id`);
