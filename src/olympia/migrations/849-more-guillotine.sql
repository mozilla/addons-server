ALTER TABLE `addons` DROP COLUMN `app_domain`;
ALTER TABLE `addons` DROP COLUMN `is_packaged`;
ALTER TABLE `addons` DROP COLUMN `enable_new_regions`;
ALTER TABLE `addons` DROP COLUMN `manifest_url`;
ALTER TABLE `addons` DROP COLUMN `premium_type`;
ALTER TABLE `addons` DROP COLUMN `make_public`;
ALTER TABLE `addons` DROP COLUMN `vip_app`;

-- Make sure the following associated indexes have been dropped:
-- addons_609c04a9 (app_domain)
-- addons_is_packaged (is_packaged)
-- addons_enable_new_regions (enable_new_regions)
-- premium_type_idx (premium_type)
