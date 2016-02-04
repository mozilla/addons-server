# Set nomination to every Version that's linked to an
# addon UNDER_REVIEW and which nomination is NULL
# See bug 717495

UPDATE `versions`
INNER JOIN `addons` ON ( `versions`.`addon_id` = addons.`id` )
INNER JOIN `files` ON (`versions`.`id` = `files`.`version_id` )
SET `versions`.`nomination` = `files`.`created`
WHERE NOT (`versions`.`deleted` = True)
AND `addons`.`status` IN (1, 3, 9)
AND `files`.`id` IS NOT NULL
AND `versions`.`nomination` IS NULL;
