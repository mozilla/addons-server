INSERT INTO waffle_flag_mkt (name, everyone, percent, superusers, staff, authenticated, rollout, testing, languages, note, created, modified)
    VALUES ('android-packaged', 0, NULL, 0, 0, 0, 0, 0, '', 'ON: packaged apps for Android can be submitted and show up in search results; OFF: packaged apps for Android are disallowed', NOW(), NOW());

INSERT INTO waffle_flag_mkt (name, everyone, percent, superusers, staff, authenticated, rollout, testing, languages, note, created, modified)
    VALUES ('desktop-packaged', 0, NULL, 0, 0, 0, 0, 0, '', 'ON: packaged apps for Desktop can be submitted and show up in search results; OFF: packaged apps for Desktop are disallowed', NOW(), NOW());
