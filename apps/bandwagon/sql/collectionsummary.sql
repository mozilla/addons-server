ALTER TABLE `collection_search_summary` ENGINE = MyISAM;

CREATE FULLTEXT INDEX `name`
    ON `collection_search_summary` (`name`, `description`)
