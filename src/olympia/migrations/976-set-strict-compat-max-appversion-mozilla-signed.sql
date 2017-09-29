UPDATE `files`
INNER JOIN `versions` ON ( `files`.`version_id` = `versions`.`id` )
INNER JOIN `addons` ON ( `versions`.`addon_id` = `addons`.`id` )
INNER JOIN `addons_users` ON ( `addons`.`id` = `addons_users`.`id` )
INNER JOIN `users` on ( `users.id` = `addons_users`.`user_id` )
SET `strict_compatibility` = TRUE
WHERE (
    `files`.`is_webextension` = FALSE
    AND `files`.`is_mozilla_signed_extension` = TRUE
    AND `users`.`email` LIKE '%@mozilla.com'
    AND `addons`.`addontype_id` IN (1, 2));

SET @firefox_star = (SELECT `id` FROM `appversions` WHERE `application_id` = 1 AND `version` = '*');

UPDATE `applications_versions`
INNER JOIN `appversions` ON ( `applications_versions`.`max` = `appversions`.`id` )
INNER JOIN `versions` ON ( `applications_versions`.`version_id` = `versions`.`id` )
INNER JOIN `files` ON ( `versions`.`id` = `files`.`version_id` )
INNER JOIN `addons_users` ON ( `versions`.`addon_id` = `addons_users`.`id` )
INNER JOIN `users` on ( `users`.`id` = `addons_users`.`user_id` )
SET `applications_versions`.`max` = @firefox_star
WHERE (`applications_versions`.`application_id` = 1
    AND `files`.`is_webextension` = FALSE
    AND `files`.`is_mozilla_signed_extension` = TRUE
    AND `users`.`email` LIKE '%@mozilla.com');
