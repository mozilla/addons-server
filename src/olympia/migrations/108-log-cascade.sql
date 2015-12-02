ALTER TABLE `log_activity` DROP FOREIGN KEY `user_id_refs_id_3fa7a30a`;

ALTER TABLE `log_activity`
    ADD CONSTRAINT `user_id_refs_id_3fa7a30a`
        FOREIGN KEY `user_id_refs_id_3fa7a30a` (`user_id`)
        REFERENCES `users` (`id`)
        ON DELETE CASCADE;

