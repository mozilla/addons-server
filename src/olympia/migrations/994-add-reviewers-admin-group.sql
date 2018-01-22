INSERT INTO `groups` (name, rules, notes, created, modified)
    VALUES ('Reviewers: Admins', 'Reviews:Admin', '', NOW(), NOW());
-- Add a few known admins using their user ids from production, as specified in
-- https://github.com/mozilla/addons-server/issues/7279
-- If they don't exist on this server, they just will be ignored.
SET @to_group := (
    SELECT `id` FROM `groups` WHERE `name` = 'Reviewers: Admins');
INSERT INTO groups_users (group_id, user_id) (
    SELECT @to_group, id FROM users WHERE id IN (4230, 4750720, 85036, 12642224));
