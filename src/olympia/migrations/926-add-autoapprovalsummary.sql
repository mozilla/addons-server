-- Note: if the migration fails for you locally, remove the 'UNSIGNED' next to version_id below.
CREATE TABLE `editors_autoapprovalsummary` (
    `created` datetime(6) NOT NULL,
    `modified` datetime(6) NOT NULL,
    `version_id` integer UNSIGNED NOT NULL PRIMARY KEY,
    `uses_custom_csp` bool NOT NULL,
    `uses_native_messaging` bool NOT NULL,
    `uses_content_script_for_all_urls` bool NOT NULL,
    `average_daily_users` integer UNSIGNED NOT NULL,
    `approved_updates` integer UNSIGNED NOT NULL,
    `verdict` smallint UNSIGNED NOT NULL
);

ALTER TABLE `editors_autoapprovalsummary` ADD CONSTRAINT `version_id_refs_id_6d27bb3c` FOREIGN KEY (`version_id`) REFERENCES `versions` (`id`);
