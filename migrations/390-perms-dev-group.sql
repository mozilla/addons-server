INSERT INTO groups (id, name, rules, notes, created, modified) VALUES
  (50056, 'Developers', 'AdminTools:View', '', NOW(), NOW());
-- Copy current users in Developers Credits into this group.
INSERT INTO groups_users (
  SELECT NULL, 50056, groups_users.user_id FROM groups, groups_users
  WHERE groups.id=groups_users.group_id AND groups.id=50046);
