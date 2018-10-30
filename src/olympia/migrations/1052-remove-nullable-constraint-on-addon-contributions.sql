-- Change NULL values to empty strings.
UPDATE `addons` SET `contributions` = '' WHERE `contributions` IS NULL;

-- Add NOT NULL constraint.
ALTER TABLE `addons` MODIFY `contributions` VARCHAR(255) NOT NULL;
