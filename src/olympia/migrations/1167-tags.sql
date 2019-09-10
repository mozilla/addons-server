ALTER TABLE `tags`
    CHANGE COLUMN `modified` `modified` DATETIME (6) NOT NULL,
    CHANGE COLUMN `id` `id` INT (10) UNSIGNED NOT NULL AUTO_INCREMENT,
    CHANGE COLUMN `num_addons` `num_addons` INT (11) NOT NULL,
    CHANGE COLUMN `created` `created` DATETIME (6) NOT NULL;
