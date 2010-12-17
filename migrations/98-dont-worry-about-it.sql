-- If these FKs don't exist, run them manually and use:
-- schematic migrations/ -u 112

ALTER TABLE `log_activity_user`
      MODIFY COLUMN `user_id` INT(11) UNSIGNED NOT NULL;

ALTER TABLE `log_activity_user`
      ADD CONSTRAINT `user_id_refs_id_e987c199`
          FOREIGN KEY `user_id_refs_id_e987c199` (`user_id`)
          REFERENCES `users` (`id`)
          ON DELETE CASCADE;
ALTER TABLE `log_activity` DROP FOREIGN KEY `user_id_refs_id_3fa7a30a`;

ALTER TABLE `log_activity`
    ADD CONSTRAINT `user_id_refs_id_3fa7a30a`
        FOREIGN KEY `user_id_refs_id_3fa7a30a` (`user_id`)
        REFERENCES `users` (`id`)
        ON DELETE CASCADE;

ALTER TABLE `log_activity_addon`
 DROP FOREIGN KEY `addon_id_refs_id_5bfa17d1`;

ALTER TABLE `log_activity_addon` ADD CONSTRAINT `addon_id_refs_id_5bfa17d1` FOREIGN KEY `addon_id_refs_id_5bfa17d1` (`addon_id`)
    REFERENCES `addons` (`id`)
    ON DELETE CASCADE;

ALTER TABLE `log_activity_addon`
    DROP FOREIGN KEY `activity_log_id_refs_id_9c20a926`;

ALTER TABLE `log_activity_addon` ADD CONSTRAINT `activity_log_id_refs_id_9c20a926` FOREIGN KEY `activity_log_id_refs_id_9c20a926` (`activity_log_id`)
    REFERENCES `log_activity` (`id`)
    ON DELETE CASCADE;

ALTER TABLE `log_activity_user`
    DROP FOREIGN KEY `activity_log_id_refs_id_4f8d99d4`;

ALTER TABLE `log_activity_user` ADD CONSTRAINT `activity_log_id_refs_id_4f8d99d4` FOREIGN KEY `activity_log_id_refs_id_4f8d99d4` (`activity_log_id`)
    REFERENCES `log_activity` (`id`)
    ON DELETE CASCADE;


