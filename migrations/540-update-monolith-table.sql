ALTER TABLE `monolith_record` DROP COLUMN `anonymous` , CHANGE COLUMN `user` `user_hash` VARCHAR(255) NOT NULL;
