DROP TABLE IF EXISTS `file_uploads`;
CREATE TABLE `file_uploads` (
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `uuid` char(32) NOT NULL PRIMARY KEY,
    `path` varchar(255) NOT NULL,
    `name` varchar(255) NOT NULL,
    `user_id` int(11) unsigned,
    `validation` longtext,
    `task_error` longtext
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

ALTER TABLE `file_uploads`
    ADD CONSTRAINT FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);
