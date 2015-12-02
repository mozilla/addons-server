RENAME TABLE `users_blacklistednickname` TO `users_blacklistedusername`;
ALTER TABLE `users_blacklistedusername` CHANGE `nickname` `username` varchar(255) NOT NULL default '';
ALTER TABLE `users_blacklistedusername` DROP KEY `nickname`;
ALTER TABLE `users_blacklistedusername` ADD UNIQUE(`username`);

-- Will take 1-3 minutes
ALTER TABLE `users`
    ADD COLUMN `username` varchar(255) UNIQUE default NULL after `email`,
    ADD COLUMN `display_name` varchar(255) default NULL after `username`;

-- This needs to be run after the convert_user_fields management command.  Since
-- that's going in at the same time as this but has to be run manually, I'm
-- leaving this commented out.
-- Query OK, 859523 rows affected (2 min 24.52 sec)

-- ALTER TABLE users CHANGE COLUMN `username` `username` varchar(255) NOT NULL;

