ALTER TABLE `discovery_discoveryitem` ADD COLUMN `recommendable` boolean NOT null DEFAULT 0;
ALTER TABLE `versions` ADD COLUMN `recommendation_approved` boolean NOT null DEFAULT 0;
