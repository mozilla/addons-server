ALTER TABLE `validation_job` ADD COLUMN `creator_id` int(11) unsigned;
ALTER TABLE `validation_job` ADD CONSTRAINT `creator_id_validation_job_key`
      FOREIGN KEY (`creator_id`) REFERENCES `users` (`id`);
