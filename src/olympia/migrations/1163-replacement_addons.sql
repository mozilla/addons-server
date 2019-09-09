ALTER TABLE `replacement_addons`
    CHANGE COLUMN `path` `path` VARCHAR (255) DEFAULT NULL,
    CHANGE COLUMN `created` `created` DATETIME (6) NOT NULL,
    CHANGE COLUMN `modified` `modified` DATETIME (6) NOT NULL,
    CHANGE COLUMN `guid` `guid` VARCHAR (255) DEFAULT NULL;
