ALTER TABLE collections_votes
    ADD UNIQUE (collection_id, user_id),
    DROP PRIMARY KEY,
    ADD COLUMN id INTEGER UNSIGNED AUTO_INCREMENT NOT NULL PRIMARY KEY FIRST;

-- Note this was tricky, I hope it turns out well for you.
ALTER TABLE collection_subscriptions
    ADD UNIQUE (collection_id, user_id),
    ADD KEY (`user_id`),
    DROP PRIMARY KEY,
    ADD COLUMN id INTEGER UNSIGNED AUTO_INCREMENT NOT NULL PRIMARY KEY FIRST;
