ALTER TABLE `app_collections` ADD COLUMN `region` integer UNSIGNED DEFAULT NULL;
ALTER TABLE `app_collections` ADD COLUMN `carrier` integer UNSIGNED DEFAULT NULL;
ALTER TABLE `app_collections` ADD COLUMN `category_id` integer;
CREATE INDEX `app_collections_region_idx` ON `app_collections` (`region`);
CREATE INDEX `app_collections_carrier_idx` ON `app_collections` (`carrier`);
CREATE INDEX `app_collections_category_id_idx` ON `app_collections` (`category_id`);
