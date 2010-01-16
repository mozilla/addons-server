ALTER TABLE `collections_votes` CHANGE COLUMN `id` `id` int(11) NOT NULL;

ALTER TABLE `collections_votes` DROP PRIMARY KEY,
    ADD PRIMARY KEY(`collection_id`, `user_id`);
