DELETE FROM groups_users WHERE group_id IN (SELECT id FROM groups WHERE name LIKE "% Localizers");
DELETE FROM groups WHERE name LIKE "% Localizers";
