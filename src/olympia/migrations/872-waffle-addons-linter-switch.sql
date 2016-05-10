INSERT INTO waffle_switch (name, active, note)
SELECT * FROM (SELECT 'addons-linter', 0, 'Waffle switch to enable addons-linter integration for WebExtensions.') as tmp
WHERE NOT EXISTS (SELECT name FROM waffle_switch WHERE name = 'addons-linter') LIMIT 1;
