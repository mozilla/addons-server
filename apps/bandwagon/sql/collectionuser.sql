ALTER TABLE `collections_users` CHANGE COLUMN `id` `id` int(11) NOT NULL;

ALTER TABLE `collections_users` DROP PRIMARY KEY,
    ADD PRIMARY KEY(`collection_id`, `user_id`);
