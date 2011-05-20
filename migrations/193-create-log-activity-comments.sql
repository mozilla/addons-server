DROP TABLE IF EXISTS log_activity_comment;

CREATE TABLE `log_activity_comment` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `activity_log_id` integer NOT NULL,
    `comments` longtext NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8
;

ALTER TABLE `log_activity_comment` ADD CONSTRAINT `activity_log_id_refs_id_4f8d99d4` FOREIGN KEY (`activity_log_id`) REFERENCES `log_activity` (`id`);
CREATE INDEX `log_activity_comment_3bf68f54` ON `log_activity_comment` (`activity_log_id`);
