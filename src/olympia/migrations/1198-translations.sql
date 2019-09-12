ALTER TABLE `translations`
    CHANGE COLUMN `autoid` `autoid` INT (10) UNSIGNED NOT NULL AUTO_INCREMENT,
    CHANGE COLUMN `created` `created` DATETIME (6) NOT NULL,
    CHANGE COLUMN `id` `id` INT (10) UNSIGNED NOT NULL,
    CHANGE COLUMN `locale` `locale` VARCHAR (10) NOT NULL,
    CHANGE COLUMN `localized_string_clean` `localized_string_clean` LONGTEXT,
    CHANGE COLUMN `localized_string` `localized_string` LONGTEXT,
    CHANGE COLUMN `modified` `modified` DATETIME (6) NOT NULL;
