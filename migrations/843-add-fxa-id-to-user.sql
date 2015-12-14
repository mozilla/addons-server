ALTER TABLE `users` ADD COLUMN `fxa_id` VARCHAR(128);
CREATE INDEX `users_fxa_id_index` ON `users` (`fxa_id`);
