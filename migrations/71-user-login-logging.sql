ALTER TABLE `users`
ADD COLUMN `last_login_ip` CHAR(45) NOT NULL DEFAULT '' AFTER `user_id`,
ADD COLUMN `last_login_attempt` DATETIME NULL DEFAULT NULL AFTER `last_login_ip`,
ADD COLUMN `last_login_attempt_ip` CHAR(45) NOT NULL DEFAULT '' AFTER `last_login_attempt`,
ADD COLUMN `failed_login_attempts` MEDIUMINT(8) UNSIGNED NOT NULL DEFAULT '0' AFTER `last_login_attempt_ip`;
