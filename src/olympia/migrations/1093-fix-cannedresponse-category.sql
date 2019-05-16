-- Set the default to "Other"
ALTER TABLE `cannedresponses`
MODIFY COLUMN `category` integer NOT NULL DEFAULT 1;

-- Correct existing canned responses.
UPDATE `cannedresponses`
SET `category` = 1
WHERE `category` = 0;

