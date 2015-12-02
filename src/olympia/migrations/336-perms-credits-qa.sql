INSERT INTO groups (id, name, rules, notes, created, modified) VALUES
  (50046, 'Developers Credits', 'None:None', '', NOW(), NOW());
INSERT INTO groups_users (
  SELECT NULL, 50046, groups_users.user_id FROM groups, groups_users
  WHERE groups.id=groups_users.group_id AND groups.name='Developers' AND groups.id < 50000);

INSERT INTO groups (id, name, rules, notes, created, modified) VALUES
  (50047, 'Past Developers Credits', 'None:None', '', NOW(), NOW());
INSERT INTO groups_users (
  SELECT NULL, 50047, groups_users.user_id FROM groups, groups_users
  WHERE groups.id=groups_users.group_id AND groups.name='Past Developers' AND groups.id < 50000);

INSERT INTO groups (id, name, rules, notes, created, modified) VALUES
  (50048, 'Other Contributors Credits', 'None:None', '', NOW(), NOW());
INSERT INTO groups_users (
  SELECT NULL, 50048, groups_users.user_id FROM groups, groups_users
  WHERE groups.id=groups_users.group_id AND groups.name='Other Contributors' AND groups.id < 50000);

UPDATE groups SET name=CONCAT(name, ' (OLD)') WHERE name='QA';
INSERT INTO groups (id, name, rules, notes, created, modified) VALUES
  (50049, 'QA', 'None:None', '', NOW(), NOW());
INSERT INTO groups_users (
  SELECT NULL, 50049, groups_users.user_id FROM groups, groups_users
  WHERE groups.id=groups_users.group_id AND groups.name='QA (OLD)' AND groups.id < 50000);
