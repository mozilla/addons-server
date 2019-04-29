ALTER TABLE `discovery_discoveryitem` ADD COLUMN `status` smallint UNSIGNED DEFAULT 0;
ALTER TABLE `versions` ADD COLUMN `recommendation_status` smallint UNSIGNED DEFAULT 0;
