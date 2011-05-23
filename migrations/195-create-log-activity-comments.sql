DROP TABLE IF EXISTS log_activity_comment;

CREATE TABLE `log_activity_comment` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `activity_log_id` int(11) NOT NULL,
    `comments` longtext NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8
;

ALTER TABLE `log_activity_comment`
      ADD CONSTRAINT FOREIGN KEY (`activity_log_id`) REFERENCES `log_activity` (`id`);

