DELETE FROM groups_users WHERE group_id IN (SELECT id FROM groups WHERE name = 'Developers');
DELETE FROM groups_users WHERE group_id IN (SELECT id FROM groups WHERE name = 'Developers Credits');
DELETE FROM groups_users WHERE group_id IN (SELECT id FROM groups WHERE name = 'Engagement');
DELETE FROM groups_users WHERE group_id IN (SELECT id FROM groups WHERE name = 'Monolith API');
DELETE FROM groups_users WHERE group_id IN (SELECT id FROM groups WHERE name = 'OAuth Partner: Flightdeck');
DELETE FROM groups_users WHERE group_id IN (SELECT id FROM groups WHERE name = 'Other Contributors Credits');
DELETE FROM groups_users WHERE group_id IN (SELECT id FROM groups WHERE name = 'Past Developers Credits');
DELETE FROM groups_users WHERE group_id IN (SELECT id FROM groups WHERE name = 'Persona Reviewer MOTD');
DELETE FROM groups_users WHERE group_id IN (SELECT id FROM groups WHERE name = 'QA');
DELETE FROM groups_users WHERE group_id IN (SELECT id FROM groups WHERE name = 'Revenue Stats Viewers');
DELETE FROM groups_users WHERE group_id IN (SELECT id FROM groups WHERE name = 'System Administrators');

DELETE FROM groups WHERE name = 'Developers';
DELETE FROM groups WHERE name = 'Developers Credits';
DELETE FROM groups WHERE name = 'Engagement';
DELETE FROM groups WHERE name = 'Monolith API';
DELETE FROM groups WHERE name = 'OAuth Partner: Flightdeck';
DELETE FROM groups WHERE name = 'Other Contributors Credits';
DELETE FROM groups WHERE name = 'Past Developers Credits';
DELETE FROM groups WHERE name = 'Persona Reviewer MOTD';
DELETE FROM groups WHERE name = 'QA';
DELETE FROM groups WHERE name = 'Revenue Stats Viewers';
DELETE FROM groups WHERE name = 'System Administrators';
