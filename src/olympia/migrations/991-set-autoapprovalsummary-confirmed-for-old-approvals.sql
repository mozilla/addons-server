UPDATE `editors_autoapprovalsummary`
INNER JOIN `versions` ON ( `editors_autoapprovalsummary`.`version_id` = `versions`.`id` )
INNER JOIN `addons` ON ( `versions`.`addon_id` = `addons`.`id` )
INNER JOIN `addons_addonapprovalscounter` ON ( `addons`.`id` = `addons_addonapprovalscounter`.`addon_id` )
SET `confirmed` = TRUE
WHERE `editors_autoapprovalsummary`.`confirmed` IS NULL
AND `addons_addonapprovalscounter`.`last_human_review` IS NOT NULL
AND `addons_addonapprovalscounter`.`last_human_review` > `editors_autoapprovalsummary`.`created`;
