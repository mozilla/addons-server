ALTER TABLE `users_denied_name`
    DROP INDEX `username`,
    CHANGE COLUMN `created` `created` DATETIME (6) NOT NULL,
    CHANGE COLUMN `modified` `modified` DATETIME (6) NOT NULL;
