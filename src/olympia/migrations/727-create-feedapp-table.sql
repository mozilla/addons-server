CREATE TABLE `mkt_feed_app` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `app_id` int(11) UNSIGNED NOT NULL,
    `description` int(11) UNSIGNED UNIQUE NULL,
    `rating_id` int(11) UNSIGNED NULL,
    `preview_id` int(11) UNSIGNED NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;
ALTER TABLE `mkt_feed_app` ADD CONSTRAINT `feed_app_preview_id`
    FOREIGN KEY (`preview_id`) REFERENCES `previews` (`id`);
ALTER TABLE `mkt_feed_app` ADD CONSTRAINT `feed_app_rating_id`
    FOREIGN KEY (`rating_id`) REFERENCES `reviews` (`id`);
ALTER TABLE `mkt_feed_item` ADD `app_id` int(11) UNSIGNED NULL;
