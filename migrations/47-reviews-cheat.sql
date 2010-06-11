ALTER TABLE `reviews`
    ADD COLUMN `previous_count` int(11) UNSIGNED DEFAULT 0,
    ADD COLUMN `is_latest` bool DEFAULT 1;
