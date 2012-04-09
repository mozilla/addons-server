-- Adjust Senior Add-on Reviewers permissions.
UPDATE groups SET rules=REPLACE(rules, 'Collections:Edit', 'CollectionStats:View') WHERE name='Senior Add-on Reviewers' AND id >= 50000;
UPDATE groups SET rules=CONCAT(rules, ',Spam:Flag') WHERE name='Senior Add-on Reviewers' AND id >= 50000;
-- Put users currently in Mozilla Corp into Stats Viewers.
INSERT INTO groups_users (
  SELECT NULL, 50001, groups_users.user_id FROM groups, groups_users
  WHERE groups.id=groups_users.group_id AND groups.id=50000);
-- Remove Mozilla Corp group.
DELETE FROM groups WHERE id=50000;
-- Rename ContributionStats to RevenueStats.
UPDATE groups SET name='Revenue Stats Viewers', rules='RevenueStats:View' WHERE name='Contribution Stats Viewers' AND id >= 50000;
-- Make Staff group.
INSERT INTO groups (id, name, rules, notes, created, modified) VALUES
  (50000, 'Staff', 'Addons:Review,Apps:Review,Personas:Review,Reviews:Edit,Addons:Edit,Addons:Configure,Users:Edit,Stats:View,CollectionStats:View', '', NOW(), NOW());
