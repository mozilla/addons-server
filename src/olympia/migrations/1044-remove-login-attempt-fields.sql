-- Those fields were NULLed and removed from the model earlier
-- in d1a5fe81fb3a90ea2fe90e4f40312dc4b3da3c9c, they are no longer used.
ALTER TABLE `users`
    DROP COLUMN `last_login_attempt_ip`,
    DROP COLUMN `failed_login_attempts`,
    DROP COLUMN `last_login_attempt`;
