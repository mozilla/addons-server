ALTER TABLE `addons` ADD COLUMN `enable_new_regions` bool NOT NULL DEFAULT 0;
CREATE INDEX `addons_enable_new_regions` ON `addons` (`enable_new_regions`);
