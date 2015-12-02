INSERT INTO groups (id, name, rules, notes, created, modified) VALUES
  (50051, 'System Administrators', 'None:None',
   'Preserved through permissions migration for future use.', NOW(), NOW());
INSERT INTO groups_users (
  SELECT NULL, 50051, groups_users.user_id FROM groups, groups_users
  WHERE groups.id=groups_users.group_id AND groups.name='sysadmins' AND groups.id < 50000);
