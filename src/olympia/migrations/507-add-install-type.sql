ALTER TABLE users_install ADD COLUMN `install_type` int(11) unsigned NOT NULL;
CREATE INDEX `users_install_install_type` ON `users_install` (`install_type`);
