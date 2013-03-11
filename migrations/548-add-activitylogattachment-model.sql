CREATE TABLE `log_activity_attachment_mkt` (
    `id` int(11) UNSIGNED AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `activity_log_id` int(11) NOT NULL,
    `filepath` varchar(255) NOT NULL,
    `description` varchar(255),
    `mimetype` varchar(255)
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;
ALTER TABLE `log_activity_attachment_mkt` ADD CONSTRAINT `activity_log_id_log_activity_attachment_key_mkt`
FOREIGN KEY (`activity_log_id`) REFERENCES `log_activity_mkt` (`id`);
