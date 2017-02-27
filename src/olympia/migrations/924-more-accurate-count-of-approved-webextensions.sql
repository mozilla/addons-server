TRUNCATE TABLE `addons_addonapprovalscounter`;

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
