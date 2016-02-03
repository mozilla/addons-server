INSERT IGNORE INTO `appversions`
SET `created`=NOW(),
    `modified`=NOW(),
    `application_id`=1,
    `version`='*',
    `version_int`='99000000200100';
