-- `adminreview` has been replaced by a new table, made nullable and removed
-- from the models in the previous tag, so it can be dropped.
ALTER TABLE `addons` DROP COLUMN `adminreview`;
