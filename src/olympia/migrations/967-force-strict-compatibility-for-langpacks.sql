UPDATE `files`
INNER JOIN `versions` ON ( `files`.`version_id` = `versions`.`id` )
INNER JOIN `addons` ON ( `versions`.`addon_id` = `addons`.`id` )
SET `strict_compatibility` = 1 
WHERE `addons`.`addontype_id` = 5;
