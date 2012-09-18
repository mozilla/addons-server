CREATE TABLE `theme_locks` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `theme_id` int(11) unsigned NOT NULL UNIQUE,
    `reviewer_id` int(11) unsigned NOT NULL,
    `expiry` datetime NOT NULL,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `theme_locks` ADD CONSTRAINT `reviewer_id_refs_id_6928eea4` FOREIGN KEY (`reviewer_id`) REFERENCES `users` (`id`);
ALTER TABLE `theme_locks` ADD CONSTRAINT `theme_id_refs_id_3202bbda` FOREIGN KEY (`theme_id`) REFERENCES `personas` (`id`);

CREATE INDEX `theme_locks_d0f17e2b` ON `theme_locks` (`reviewer_id`);
