INSERT INTO `denied_guids`
    (guid, created, modified, comments)
    SELECT `guid`, NOW(), NOW(), ''  from `addons` WHERE addontype_id in (2, 6) AND `guid` IS NOT NULL
    ON DUPLICATE KEY UPDATE modified = NOW();
