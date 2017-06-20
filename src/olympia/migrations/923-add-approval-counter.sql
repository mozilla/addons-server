-- Note: if the migration fails for you locally, remove the 'unsigned' next to addon_id below.
CREATE TABLE `addons_addonapprovalscounter` (
    `created` datetime(6) NOT NULL,
    `modified` datetime(6) NOT NULL,
    `addon_id` integer UNSIGNED NOT NULL PRIMARY KEY,
    `counter` integer UNSIGNED NOT NULL
);
ALTER TABLE `addons_addonapprovalscounter` ADD CONSTRAINT `addon_id_refs_id_8fcb7166` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);

-- Fill the newly created table the best we can.
INSERT INTO `addons_addonapprovalscounter` (`addon_id`, `counter`, `created`, `modified`)
SELECT DISTINCT(`addons`.`id`), (
        -- In this subquery, we count the number of public, non deleted, listed versions that are webextensions, for
        -- each add-on the main query is processing.
        SELECT COUNT(*) FROM `versions`
        INNER JOIN `files` ON ( `versions`.`id` = `files`.`version_id` AND `files`.`status` = 4 AND `files`.`is_webextension` = 1)
        WHERE `deleted` = 0 AND `channel` = 2 AND `addon_id` = `addons`.`id`
    ) AS `version_count`, NOW(), NOW()
    FROM `addons` INNER JOIN `versions` ON ( `addons`.`current_version` = `versions`.`id` )
    INNER JOIN `files` ON ( `versions`.`id` = `files`.`version_id` )
    WHERE `addons`.`status` = 4 AND `addons`.`inactive` = false AND `files`.`is_webextension` = 1;
