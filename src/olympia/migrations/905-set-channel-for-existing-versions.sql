UPDATE `versions` INNER JOIN `addons` ON ( `versions`.`addon_id` = `addons`.`id` ) SET `channel` = 1 WHERE `addons`.`is_listed` = false;
UPDATE `versions` INNER JOIN `addons` ON ( `versions`.`addon_id` = `addons`.`id` ) SET `channel` = 2 WHERE `addons`.`is_listed` = true;
