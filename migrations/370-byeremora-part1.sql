-- Now that remora is gone we can clean up all the old cruft



DROP TABLE `addons_pledges`;
DROP TABLE `cache`;
DROP TABLE `collection_addon_recommendations`;
DROP TABLE `facebook_data`;
DROP TABLE `facebook_detected`;
DROP TABLE `facebook_favorites`;
DROP TABLE `facebook_sessions`;
DROP TABLE `facebook_users`;
DROP TABLE `fizzypop`;
DROP TABLE `howto_votes`;
DROP TABLE `reviewratings`;
DROP TABLE `sphinx_index_feed_tmp`;

DROP TABLE `collections_search_summary`;
DROP TABLE `text_search_summary`;
DROP TABLE `versions_summary`;

-- Removed from code in separate commit
DROP TABLE `test_cases`;
DROP TABLE `test_groups`;
DROP TABLE `test_results`;
DROP TABLE `test_results_cache`;

-- Removed from code in separate commit
ALTER TABLE `applications` DROP COLUMN `icondata`;
ALTER TABLE `applications` DROP COLUMN `icontype`;
ALTER TABLE `platforms` DROP COLUMN `icondata`;
ALTER TABLE `platforms` DROP COLUMN `icontype`;

ALTER TABLE `addons` DROP COLUMN `binary`;

-- Removed from code in separate commit
ALTER TABLE `categories` DROP FOREIGN KEY `categories_ibfk_4`;
ALTER TABLE `categories` DROP COLUMN `description`;

ALTER TABLE `collections` DROP COLUMN `access`;

ALTER TABLE `users` DROP COLUMN `firstname`,
                    DROP COLUMN `nickname`,
                    DROP COLUMN `lastname`,
                    DROP COLUMN `sandboxshown`;

ALTER TABLE `users_tags_addons` DROP COLUMN `user_id`;

DELETE FROM `config` WHERE `key` IN (
    'api_disabled', 'cron_debug_enabled', 'emailchange_secret',
    'firefox_notice_url', 'firefox_notice_version', 'paypal_disabled',
    'queues_disabled', 'search_disabled', 'site_notice', 'stats_disabled',
    'stats_updating', 'submissions_disabled', 'validation_disabled');

