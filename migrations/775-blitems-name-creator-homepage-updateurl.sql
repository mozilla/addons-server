ALTER TABLE blitems
    ADD COLUMN `name` VARCHAR(255),
    ADD COLUMN `creator` VARCHAR(255),
    ADD COLUMN `homepage_url` VARCHAR(200),
    ADD COLUMN `update_url` VARCHAR(200);
