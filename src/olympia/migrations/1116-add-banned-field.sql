ALTER TABLE `users` ADD COLUMN `banned` datetime NULL;

UPDATE `users` SET `banned` = `modified` WHERE `deleted` = TRUE AND `email` IS NOT NULL AND `fxa_id` IS NOT NULL;
