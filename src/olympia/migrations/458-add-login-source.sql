ALTER TABLE `users` ADD COLUMN `source` integer(11) NOT NULL DEFAULT 0;

-- apps/constant/base LOGIN_SOURCE_*

UPDATE `users` SET `source`=1 WHERE `password`='' and `notes`='__market__';
