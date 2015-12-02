INSERT INTO groups VALUES (50002, 'Add-on Reviewers', 'Addons:Review', NOW(), NOW());
INSERT INTO groups VALUES (50003, 'App Reviewers', 'Apps:Review', NOW(), NOW());
INSERT INTO groups VALUES (50004, 'Persona Reviewers', 'Personas:Review', NOW(), NOW());
-- We will append to this group as we edit more permissions.
INSERT INTO groups VALUES (50005, 'Senior Add-on Reviewers', 'Addons:Review', NOW(), NOW());


INSERT INTO groups_users (
	SELECT NULL, 50002, groups_users.user_id FROM groups, groups_users
	WHERE groups.id=groups_users.group_id AND groups.name='Editors' AND groups.id < 50000);
INSERT INTO groups_users (
	SELECT NULL, 50004, groups_users.user_id FROM groups, groups_users
	WHERE groups.id=groups_users.group_id AND groups.name='Persona Reviewer' AND groups.id < 50000);
INSERT INTO groups_users (
	SELECT NULL, 50005, groups_users.user_id FROM groups, groups_users
	WHERE groups.id=groups_users.group_id AND groups.name='Senior Editors' AND groups.id < 50000);
