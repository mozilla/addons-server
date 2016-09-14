CREATE TABLE `log_activity_tokens` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `version_id` int(11) NOT NULL,
    `user_id` int(11) NOT NULL,
    `uuid` char(32) NOT NULL UNIQUE,
    `use_count` integer UNSIGNED NOT NULL
) DEFAULT CHARSET=utf8;

ALTER TABLE `log_activity_tokens` ADD CONSTRAINT `log_activity_tokens_user`
FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);
ALTER TABLE `log_activity_tokens` ADD CONSTRAINT `log_activity_tokens_version`
FOREIGN KEY (`version_id`) REFERENCES `versions` (`id`);
