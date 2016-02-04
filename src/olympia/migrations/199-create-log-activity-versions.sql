DROP TABLE IF EXISTS log_activity_version;

CREATE TABLE `log_activity_version` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `activity_log_id` int(11) NOT NULL,
    `version_id` int(11) UNSIGNED NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8
;

ALTER TABLE `log_activity_version`
      ADD CONSTRAINT FOREIGN KEY (`activity_log_id`) REFERENCES `log_activity` (`id`);

ALTER TABLE `log_activity_version`
      ADD CONSTRAINT FOREIGN KEY (`version_id`) REFERENCES `versions` (`id`);
