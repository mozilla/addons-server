RENAME TABLE preinstall_test_plan TO preload_test_plans;

ALTER TABLE preload_test_plans ADD COLUMN status tinyint(1) UNSIGNED NOT NULL;

UPDATE `waffle_switch_mkt` SET name='preload-apps' WHERE name='preinstall-apps';

UPDATE `groups` SET rules=CONCAT(rules, ',Operators:*') WHERE name='Operators';
