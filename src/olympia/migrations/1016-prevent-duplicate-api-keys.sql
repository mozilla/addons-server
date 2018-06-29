-- First, disable all active API keys from users who have multiple active API
-- keys. We can't know which one they expected to work, and they couldn't use
-- them before anyway because of MultipleObjectsReturned exception.
-- The double subquery is here to let MySQL update and select from the same
-- table by creating a temporary one.
UPDATE `api_key` SET `is_active` = 0 WHERE `user_id` IN (
    SELECT `user_id` FROM (
        SELECT `user_id` FROM `api_key`
        GROUP BY `user_id` HAVING SUM(is_active) > 1
        ORDER BY `user_id`)
    AS `temp`);

-- Allow NULLs for is_active.
ALTER TABLE `api_key` MODIFY COLUMN `is_active` tinyint(1) NULL;

-- Set all is_active=false to nulls to allow for the unique constraint to be
-- added.
UPDATE `api_key` SET `is_active` = NULL WHERE `is_active` = false;

-- Add the unique constraint, preventing users from having more than one active
-- key at the same time.
ALTER TABLE `api_key` ADD UNIQUE INDEX(`user_id`, `is_active`);
