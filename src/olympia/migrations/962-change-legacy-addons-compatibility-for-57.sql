DROP PROCEDURE IF EXISTS set_min_and_max_compatibility;

DELIMITER ';;'

CREATE PROCEDURE set_min_and_max_compatibility() BEGIN
    -- Enable strict compatibility for all extensions/themes that are not webextensions.
    UPDATE `files`
    INNER JOIN `versions` ON ( `files`.`version_id` = `versions`.`id` )
    INNER JOIN `addons` ON ( `versions`.`addon_id` = `addons`.`id` )
    SET `strict_compatibility` = TRUE
    WHERE (`files`.`is_webextension` = FALSE AND `addons`.`addontype_id` IN (1, 2));

    -- All legacy add-ons must have a max below Firefox 57.
    -- Start by recording the new AppVersions we're going to set for those add-ons.
    SET @firefox_56 = (SELECT `id` FROM `appversions` WHERE `application_id` = 1 AND `version` = '56.0');
    SET @firefox_for_android_56 = (SELECT `id` FROM `appversions` WHERE `application_id` = 61 AND `version` = '56.0');
    SET @firefox_56_and_higher = (SELECT `id` FROM `appversions` WHERE `application_id` = 1 AND `version` = '56.*');
    SET @firefox_for_android_56_and_higher = (SELECT `id` FROM `appversions` WHERE `application_id` = 61 AND `version` = '56.*');

    -- Update ApplicationsVersions to set the new minimum version, if we're dealing with compatibility info
    -- targeting Firefox/Firefox for Android >= 57.0 and not being webextensions. There should not be many of
    -- them, but it's technically possible, since we let developers pick even '*' as a min version.
    IF (@firefox_56 IS NOT NULL) THEN
        UPDATE `applications_versions`
        INNER JOIN `appversions` ON ( `applications_versions`.`min` = `appversions`.`id` )
        INNER JOIN `versions` ON ( `applications_versions`.`version_id` = `versions`.`id` )
        INNER JOIN `files` ON ( `versions`.`id` = `files`.`version_id` )
        SET `applications_versions`.`min` = @firefox_56
        WHERE (`applications_versions`.`application_id` = 1
            AND `files`.`is_webextension` = False
            AND `appversions`.`version_int` >= 57000000000000);
    END IF;

    IF (@firefox_for_android_56 IS NOT NULL) THEN
        UPDATE `applications_versions`
        INNER JOIN `appversions` ON ( `applications_versions`.`min` = `appversions`.`id` )
        INNER JOIN `versions` ON ( `applications_versions`.`version_id` = `versions`.`id` )
        INNER JOIN `files` ON ( `versions`.`id` = `files`.`version_id` )
        SET `applications_versions`.`min` = @firefox_for_android_56
        WHERE (`applications_versions`.`application_id` = 61
            AND `files`.`is_webextension` = False
            AND `appversions`.`version_int` >= 57000000000000);
    END IF;

    -- Do the same thing for the max version now. Here, we can use 56.* as the last version.
    IF (@firefox_56_and_higher IS NOT NULL) THEN
        UPDATE `applications_versions`
        INNER JOIN `appversions` ON ( `applications_versions`.`max` = `appversions`.`id` )
        INNER JOIN `versions` ON ( `applications_versions`.`version_id` = `versions`.`id` )
        INNER JOIN `files` ON ( `versions`.`id` = `files`.`version_id` )
        SET `applications_versions`.`max` = @firefox_56_and_higher
        WHERE (`applications_versions`.`application_id` = 1
            AND `files`.`is_webextension` = False
            AND `appversions`.`version_int` >= 57000000000000);
    END IF;

    IF (@firefox_for_android_56_and_higher IS NOT NULL) THEN
        UPDATE `applications_versions`
        INNER JOIN `appversions` ON ( `applications_versions`.`max` = `appversions`.`id` )
        INNER JOIN `versions` ON ( `applications_versions`.`version_id` = `versions`.`id` )
        INNER JOIN `files` ON ( `versions`.`id` = `files`.`version_id` )
        SET `applications_versions`.`max` = @firefox_for_android_56_and_higher
        WHERE (`applications_versions`.`application_id` = 61
            AND `files`.`is_webextension` = False
            AND `appversions`.`version_int` >= 57000000000000);
    END IF;
END;;

DELIMITER ';'

CALL set_min_and_max_compatibility();

DROP PROCEDURE IF EXISTS set_min_and_max_compatibility;
