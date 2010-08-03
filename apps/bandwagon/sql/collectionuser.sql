ALTER TABLE `collections_users`
    CHANGE COLUMN `id` `id` int(11) NOT NULL DEFAULT 0;

ALTER TABLE `collections_users` DROP PRIMARY KEY,
    ADD PRIMARY KEY(`collection_id`, `user_id`);
