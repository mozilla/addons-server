CREATE TABLE `mkt_feed_item` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `category_id` int(11) UNSIGNED NULL,
    `region` int(11) UNSIGNED NULL,
    `carrier` int(11) UNSIGNED NULL,
    `collection_id` int(11) UNSIGNED NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `mkt_feed_item` ADD CONSTRAINT `feed_item_category_id`
    FOREIGN KEY (`category_id`) REFERENCES `categories` (`id`);
ALTER TABLE `mkt_feed_item` ADD CONSTRAINT `feed_item_collection_id`
    FOREIGN KEY (`collection_id`) REFERENCES `app_collections` (`id`);

CREATE INDEX mkt_feed_item_region_carrier_idx
    ON mkt_feed_item (`region`, `carrier`);
CREATE INDEX mkt_feed_item_category_region_carrier_idx
    ON mkt_feed_item (`category_id`, `region`, `carrier`);
