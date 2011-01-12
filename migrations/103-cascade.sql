SET FOREIGN_KEY_CHECKS=0;

ALTER TABLE `log_activity_user`
      DROP FOREIGN KEY `user_id_refs_id_e987c199`,
      MODIFY COLUMN `user_id` INT(11) UNSIGNED NOT NULL;

ALTER TABLE `log_activity_user`
      ADD CONSTRAINT `user_id_refs_id_e987c199`
          FOREIGN KEY `user_id_refs_id_e987c199` (`user_id`)
          REFERENCES `users` (`id`)
          ON DELETE CASCADE;

SET FOREIGN_KEY_CHECKS=1;
