-- Nullify obsolete fields on users and collections table, we'll remove them
-- in a follow-up commit after the code using them as been removed.
ALTER TABLE `users` MODIFY COLUMN `display_collections_fav` tinyint unsigned;
ALTER TABLE `collections` MODIFY COLUMN `rating` float,
                          MODIFY COLUMN `downvotes` int,
                          MODIFY COLUMN `upvotes` int,
                          MODIFY COLUMN `monthly_subscribers` int,
                          MODIFY COLUMN `downloads` int,
                          MODIFY COLUMN `subscribers` int,
                          MODIFY COLUMN `weekly_subscribers` int;
-- Similarly, truncate tables we'll remove later.
TRUNCATE TABLE `collection_subscriptions`;
TRUNCATE TABLE `collections_votes`;
TRUNCATE TABLE `stats_addons_collections_counts`;
TRUNCATE TABLE `stats_collections_counts`;
TRUNCATE TABLE `stats_collections`;
