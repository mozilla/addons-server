-- note: the column is added as nullable, a command will backfill values for
-- existing users.
ALTER TABLE `users` ADD COLUMN `auth_id` integer UNSIGNED;
