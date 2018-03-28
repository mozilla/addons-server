INSERT INTO groups (name, rules, created, modified) VALUES ('Content Curators', 'Admin:Curation', NOW(), NOW());
UPDATE groups SET rules=REPLACE(rules, 'AdminTools:View', 'Admin:Tools') WHERE name='Staff';
