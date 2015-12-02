-- Now that remora is gone we can clean up all the old cruft



DROP TABLE IF EXISTS `addons_pledges`;
DROP TABLE IF EXISTS `cache`;
DROP TABLE IF EXISTS `collection_addon_recommendations`;
DROP TABLE IF EXISTS `facebook_data`;
DROP TABLE IF EXISTS `facebook_detected`;
DROP TABLE IF EXISTS `facebook_favorites`;
DROP TABLE IF EXISTS `facebook_sessions`;
DROP TABLE IF EXISTS `facebook_users`;
DROP TABLE IF EXISTS `fizzypop`;
DROP TABLE IF EXISTS `howto_votes`;
DROP TABLE IF EXISTS `reviewratings`;
DROP TABLE IF EXISTS `sphinx_index_feed_tmp`;

DROP TABLE IF EXISTS `collections_search_summary`;
DROP TABLE IF EXISTS `text_search_summary`;
DROP TABLE IF EXISTS `versions_summary`;

-- Removed from code in separate commit
ALTER TABLE `test_cases` DROP FOREIGN KEY `test_cases_ibfk_1`;
ALTER TABLE `test_results` DROP FOREIGN KEY `test_results_ibfk_1`;
ALTER TABLE `test_results` DROP FOREIGN KEY `test_results_ibfk_2`;
DROP TABLE IF EXISTS `test_cases`;
DROP TABLE IF EXISTS `test_groups`;
DROP TABLE IF EXISTS `test_results`;
DROP TABLE IF EXISTS `test_results_cache`;

-- Removed from code in separate commit
ALTER TABLE `applications` DROP COLUMN `icondata`;
ALTER TABLE `applications` DROP COLUMN `icontype`;
ALTER TABLE `platforms` DROP COLUMN `icondata`;
ALTER TABLE `platforms` DROP COLUMN `icontype`;

ALTER TABLE `addons` DROP COLUMN `binary`;

-- Removed from code in separate commit
ALTER TABLE `categories` DROP FOREIGN KEY `categories_ibfk_1`;
ALTER TABLE `categories` DROP FOREIGN KEY `categories_ibfk_2`;
ALTER TABLE `categories` DROP FOREIGN KEY `categories_ibfk_3`;
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

