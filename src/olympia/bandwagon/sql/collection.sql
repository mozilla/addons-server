-- Until Django supports arbitrary indexes we use .sql

CREATE INDEX `collection_application_index_1`
    ON `collections` (`application_id`)
