ALTER TABLE `discovery_discoveryitem`
    ADD COLUMN `position` smallint UNSIGNED DEFAULT 0,
    ADD COLUMN `position_china` smallint UNSIGNED DEFAULT 0;
