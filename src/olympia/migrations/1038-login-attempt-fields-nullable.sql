-- Those fields are no longer useful, NULL them so that we can safely remove
-- them at a later date.
ALTER TABLE `users` MODIFY `last_login_attempt_ip` char(45), MODIFY `failed_login_attempts` mediumint(8) unsigned;
