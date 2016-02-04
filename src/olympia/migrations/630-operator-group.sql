INSERT INTO groups (name, rules, created, modified, notes)
        VALUES ('Operators', 'Lookup:View,AppLookup:View', NOW(), NOW(), 'For operators to perform app lookups');

UPDATE `groups` SET rules=CONCAT(rules, ',Lookup:View,AppLookup:View') WHERE name='Support Staff';
