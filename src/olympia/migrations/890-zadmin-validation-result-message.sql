CREATE TABLE `zadmin_validationresultmessage` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `validation_job_id` integer NOT NULL,
    `message_id` varchar(256) NOT NULL,
    `message` longtext NOT NULL,
    `compat_type` varchar(256) NOT NULL,
    `addons_affected` integer UNSIGNED NOT NULL
);

ALTER TABLE `zadmin_validationresultmessage` ADD CONSTRAINT `validation_job_id_refs_id_01ccc917` FOREIGN KEY (`validation_job_id`) REFERENCES `validation_job` (`id`);

CREATE TABLE `zadmin_validationresultaffectedaddon` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `addon_id` integer NOT NULL,
    `validation_result_message_id` integer NOT NULL
);

ALTER TABLE `zadmin_validationresultaffectedaddon` ADD CONSTRAINT `addon_id_refs_id_c0c27c60` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
ALTER TABLE `zadmin_validationresultaffectedaddon` ADD CONSTRAINT `validation_result_message_id_refs_id_de730cf6` FOREIGN KEY (`validation_result_message_id`) REFERENCES `zadmin_validationresultmessage` (`id`);
