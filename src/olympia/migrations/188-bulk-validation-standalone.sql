-- Nothing in production yet:
DELETE FROM validation_result;
ALTER TABLE validation_result DROP FOREIGN KEY `file_validation_id_refs_id_36081e0`;
ALTER TABLE validation_result DROP COLUMN file_validation_id;
ALTER TABLE validation_result ADD COLUMN `file_id` int(11) unsigned NOT NULL;
ALTER TABLE validation_result ADD COLUMN `valid` bool NOT NULL;
ALTER TABLE validation_result ADD COLUMN `errors` int(11) unsigned NULL;
ALTER TABLE validation_result ADD COLUMN `warnings` int(11) unsigned NULL;
ALTER TABLE validation_result ADD COLUMN `notices` int(11) unsigned NULL;
ALTER TABLE validation_result ADD COLUMN `validation` longtext NULL;
ALTER TABLE `validation_result` ADD CONSTRAINT `file_id_refs_id_35f23f5` FOREIGN KEY (`file_id`) REFERENCES `files` (`id`);
CREATE INDEX `validation_result_2243e3be` ON `validation_result` (`file_id`);
