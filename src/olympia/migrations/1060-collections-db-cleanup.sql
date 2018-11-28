DROP TABLE IF EXISTS `collection_subscriptions`;
DROP TABLE IF EXISTS `collections_votes`;
DROP TABLE IF EXISTS `stats_addons_collections_counts`;
DROP TABLE IF EXISTS `stats_collections_counts`;
DROP TABLE IF EXISTS `stats_collections`;
    
ALTER TABLE `users` DROP COLUMN `display_collections_fav`;

ALTER TABLE `collections` DROP COLUMN `rating`, DROP COLUMN `downvotes`, DROP COLUMN `upvotes`, DROP COLUMN `monthly_subscribers`, DROP COLUMN `downloads`, DROP COLUMN `subscribers`, DROP COLUMN `weekly_subscribers`, DROP COLUMN `icontype`;
