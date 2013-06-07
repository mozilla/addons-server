INSERT INTO waffle_flag_mkt (name, everyone, percent, superusers, staff, authenticated, rollout, note, created, modified)
    VALUES ('allow-b2g-paid-submission', 0, NULL, 0, 0, 0, 0, 'Enable this to allow paid apps in the submission process.', NOW(), NOW());
UPDATE waffle_flag_mkt SET everyone = (SELECT active FROM waffle_switch_mkt WHERE name = 'allow-b2g-paid-submission') WHERE name = 'allow-b2g-paid-submission';
DELETE FROM waffle_switch_mkt WHERE name = 'allow-b2g-paid-submission';
