CREATE TABLE `log_activity_group` (
    `id` int(11) UNSIGNED AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `activity_log_id` int(11) NOT NULL,
    `group_id` int(11) unsigned NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `log_activity_group` ADD CONSTRAINT `group_id_refs_id_757b3ceb`
FOREIGN KEY (`group_id`) REFERENCES `groups` (`id`) ON DELETE CASCADE;

ALTER TABLE `log_activity_group` ADD CONSTRAINT `activity_log_id_refs_id_15e06f3d`
FOREIGN KEY (`activity_log_id`) REFERENCES `log_activity` (`id`) ON DELETE CASCADE;
