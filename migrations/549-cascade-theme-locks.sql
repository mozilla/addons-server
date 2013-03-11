ALTER TABLE `theme_locks` DROP FOREIGN KEY `reviewer_id_refs_id_6928eea4`;
ALTER TABLE `theme_locks` DROP FOREIGN KEY `theme_id_refs_id_3202bbda`;

ALTER TABLE `theme_locks` ADD CONSTRAINT `reviewer_id_refs_id_fk`
    FOREIGN KEY (`reviewer_id`) REFERENCES `users` (`id`) ON DELETE CASCADE;
ALTER TABLE `theme_locks` ADD CONSTRAINT `theme_id_refs_id_fk`
    FOREIGN KEY (`theme_id`) REFERENCES `personas` (`id`) ON DELETE CASCADE;
