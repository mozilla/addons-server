ALTER TABLE `discovery_discoveryitem` ADD COLUMN `recommendable` boolean DEFAULT False;
ALTER TABLE `versions` ADD COLUMN `recommendation_approved` boolean DEFAULT False;
