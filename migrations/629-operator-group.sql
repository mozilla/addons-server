INSERT INTO groups (name, rules, created, modified)
        VALUES ('Operators', 'Lookup:View,AppLookup:View', NOW(), NOW());

UPDATE `groups` SET rules=CONCAT(rules, ',Lookup:View,AppLookup:View') WHERE name='Support Staff';
