CREATE TABLE `log_activity_emails` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `messageid` char(255) NOT NULL UNIQUE
) DEFAULT CHARSET=utf8;

ALTER TABLE `log_activity_tokens` ADD UNIQUE KEY (`version_id`, `user_id`);
