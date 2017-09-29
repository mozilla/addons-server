 UPDATE `files`
 SET `strict_compatibility` = FALSE
 WHERE `is_mozilla_signed_extension` = TRUE;


SET @firefox_star = (SELECT `id` FROM `appversions` WHERE `application_id` = 1 AND `version` = '*');

UPDATE `applications_versions`
INNER JOIN `appversions` ON ( `applications_versions`.`max` = `appversions`.`id` )
INNER JOIN `versions` ON ( `applications_versions`.`version_id` = `versions`.`id` )
INNER JOIN `files` ON ( `versions`.`id` = `files`.`version_id` )
SET `applications_versions`.`max` = @firefox_star
WHERE (`applications_versions`.`application_id` = 1
    AND `files`.`is_webextension` = FALSE
    AND `files`.`is_mozilla_signed_extension` = TRUE);
