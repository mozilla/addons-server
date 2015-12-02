INSERT INTO groups VALUES (50000, 'Mozilla Corporation', 'Stats:View', NOW(), NOW());
INSERT INTO groups VALUES (50001, 'Statistic Viewers', 'Stats:View,CollectionStats:View', NOW(), NOW());

INSERT INTO groups_users (
	SELECT NULL, 50000, groups_users.user_id FROM groups, groups_users 
	WHERE groups.id=groups_users.group_id AND groups.name='Mozilla Corporation' AND groups.id < 50000);
INSERT INTO groups_users (
	SELECT NULL, 50001, groups_users.user_id FROM groups, groups_users 
	WHERE groups.id=groups_users.group_id AND groups.name='Statistic Viewers' AND groups.id < 50000);
