ALTER TABLE users_install ADD COLUMN email varchar(255) NOT NULL;
ALTER TABLE users_install ADD COLUMN premium_type integer UNSIGNED;
CREATE INDEX `users_install_email` ON `users_install` (`email`);
