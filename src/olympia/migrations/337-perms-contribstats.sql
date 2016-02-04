UPDATE groups SET name=CONCAT(name, ' (OLD)') WHERE name='Contributions Stats Viewers';
INSERT INTO groups (id, name, rules, notes, created, modified) VALUES
  (50050, 'Contribution Stats Viewers', 'ContributionStats:View', '', NOW(), NOW());
INSERT INTO groups_users (
  SELECT NULL, 50050, groups_users.user_id FROM groups, groups_users
  WHERE groups.id=groups_users.group_id AND groups.name='Contributions Stats Viewers' AND groups.id < 50000);
