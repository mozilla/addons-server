ALTER TABLE `mkt_feed_app`
    DROP COLUMN `rating_id`,
    DROP FOREIGN KEY `feed_app_rating_id`,
    ADD (`pullquote_rating` int(11) UNSIGNED NULL,
         `pullquote_text` int(11) UNSIGNED UNIQUE NULL,
         `pullquote_attribution` int(11) UNSIGNED UNIQUE NULL);
