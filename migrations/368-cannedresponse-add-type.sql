ALTER TABLE `cannedresponses` ADD COLUMN `type` integer UNSIGNED NOT NULL;
-- All currently existing canned responses belong to addons (type=1).
UPDATE `cannedresponses` SET `type`=1;
