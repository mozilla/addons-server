-- Make the old field nullable to prepare for its future removal.
ALTER TABLE `addons` MODIFY COLUMN `adminreview` tinyint(1) NULL;
-- Create the new table.
-- Note: if the migration fails for you locally, remove the 'UNSIGNED' next to addon_id below.
CREATE TABLE `addons_addonreviewerflags` (
    `created` datetime(6) NOT NULL,
    `modified` datetime(6) NOT NULL,
    `addon_id` integer UNSIGNED NOT NULL PRIMARY KEY,
    `needs_admin_code_review` bool NOT NULL,
    `needs_admin_content_review` bool NOT NULL
)
;
ALTER TABLE `addons_addonreviewerflags` ADD CONSTRAINT `addon_id_refs_id_7a280313` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
-- Insert all previous admin code review flags in the new table. There are no previous admin content review flags.
INSERT INTO `addons_addonreviewerflags` (`created`, `modified`, `addon_id`, `needs_admin_code_review`, `needs_admin_content_review`)
    SELECT NOW(), NOW(), id, true, false FROM `addons` WHERE `adminreview` = true;
