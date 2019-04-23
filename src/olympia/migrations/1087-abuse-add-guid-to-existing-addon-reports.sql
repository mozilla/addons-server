UPDATE `abuse_reports`
    INNER JOIN `addons` ON (`abuse_reports`.`addon_id` = `addons`.`id`)
    SET `abuse_reports`.`guid` = `addons`.`guid`
    WHERE `abuse_reports`.`addon_id` IS NOT NULL
    AND `abuse_reports`.`guid` IS NULL;
