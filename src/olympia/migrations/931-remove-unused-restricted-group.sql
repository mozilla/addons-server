DELETE groups_users FROM groups_users INNER JOIN groups ON groups.id = groups_users.group_id WHERE groups.rules = "Restricted:UGC";
DELETE FROM groups WHERE groups.rules = "Restricted:UGC" LIMIT 1;
