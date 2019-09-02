INSERT INTO `denied_guids`
    (guid, created, modified, comments)
    SELECT `guid`, NOW(), NOW(), 'Hard-deleted xul-theme/addon-lang-pack.  See #12212'  from `addons` WHERE addontype_id in (2, 6) AND `guid` IS NOT NULL
    ON DUPLICATE KEY UPDATE modified = NOW();
