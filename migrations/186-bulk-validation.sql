CREATE TABLE `validation_job` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `application_id` int(11) unsigned NOT NULL,
    `curr_max_version_id` int(11) unsigned NOT NULL,
    `target_version_id` int(11) unsigned NOT NULL,
    `finish_email` varchar(255),
    `completed` datetime
)
;
ALTER TABLE `validation_job`
    ADD CONSTRAINT `application_id_refs_id_e6541345`
    FOREIGN KEY (`application_id`) REFERENCES `applications` (`id`);
ALTER TABLE `validation_job`
    ADD CONSTRAINT `curr_max_version_id_refs_id_c959f479`
    FOREIGN KEY (`curr_max_version_id`) REFERENCES `appversions` (`id`);
ALTER TABLE `validation_job`
    ADD CONSTRAINT `target_version_id_refs_id_c959f479`
    FOREIGN KEY (`target_version_id`) REFERENCES `appversions` (`id`);
CREATE TABLE `validation_result` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `validation_job_id` int(11) unsigned NOT NULL,
    `file_validation_id` int(11) unsigned,
    `task_error` longtext,
    `completed` datetime
)
;
ALTER TABLE `validation_result`
    ADD CONSTRAINT `validation_job_id_refs_id_3b0311f8`
    FOREIGN KEY (`validation_job_id`) REFERENCES `validation_job` (`id`);
ALTER TABLE `validation_result`
    ADD CONSTRAINT `file_validation_id_refs_id_36081e0`
    FOREIGN KEY (`file_validation_id`) REFERENCES `file_validation` (`id`);
CREATE INDEX `validation_job_398529ef` ON `validation_job` (`application_id`);
CREATE INDEX `validation_job_cc1f3b9a` ON `validation_job` (`curr_max_version_id`);
CREATE INDEX `validation_job_1cf8b594` ON `validation_job` (`target_version_id`);
CREATE INDEX `validation_job_e490d511` ON `validation_job` (`completed`);
CREATE INDEX `validation_result_61162f45` ON `validation_result` (`validation_job_id`);
CREATE INDEX `validation_result_4878d95` ON `validation_result` (`file_validation_id`);
CREATE INDEX `validation_result_e490d511` ON `validation_result` (`completed`);
