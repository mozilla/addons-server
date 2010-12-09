ALTER TABLE `log_activity_user`
      MODIFY COLUMN `user_id` INTEGER UNSIGNED NOT NULL;

ALTER TABLE `log_activity_user` DROP FOREIGN KEY `user_id_refs_id_e987c199`;

ALTER TABLE `remora`.`log_activity_user`
      ADD CONSTRAINT `user_id_refs_id_e987c199`
          FOREIGN KEY `user_id_refs_id_e987c199` (`user_id`)
          REFERENCES `users` (`id`)
          ON DELETE CASCADE;
