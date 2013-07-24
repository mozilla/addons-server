INSERT INTO groups (name, rules, created, modified, notes)
        VALUES ('Statistics Viewers', 'Stats:View', NOW(), NOW(), 'To view consumer statistic pages and access statistics API.');

UPDATE `groups` SET rules=CONCAT(rules, ',Stats:View') WHERE name='Staff';
