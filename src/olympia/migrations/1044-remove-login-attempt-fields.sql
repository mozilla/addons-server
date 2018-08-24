-- Those fields were NULLed and removed from the model earlier, they are no longer used.
ALTER TABLE `users` DROP COLUMN `last_login_attempt_ip`, DROP COLUMN `failed_login_attempts`, DROP COLUMN `last_login_attempt`;
