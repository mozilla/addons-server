UPDATE `groups` SET `name` = 'Reviewers: Legacy', `rules` = 'Addons:Review'
    WHERE name = 'Add-on Reviewers' LIMIT 1;
UPDATE `groups` SET `name` = 'Reviewers: Unlisted'
    WHERE name = 'Unlisted Add-on Reviewers' LIMIT 1;
UPDATE `groups` SET `name` = 'Reviewers: Themes'
    WHERE name = 'Persona Reviewers' LIMIT 1;
DELETE `groups_users` FROM `groups_users` INNER JOIN `groups`
    ON ( `groups_users`.`group_id` = `groups`.`id` )
    WHERE `groups`.`name` = 'Senior Add-on Reviewers';
DELETE `groups_users` FROM `groups_users` INNER JOIN `groups`
    ON ( `groups_users`.`group_id` = `groups`.`id` )
    WHERE `groups`.`name` = 'Senior Personas Reviewers';
DELETE FROM `groups` WHERE `name` = 'Senior Add-on Reviewers' LIMIT 1;
DELETE FROM `groups` WHERE `name` = 'Senior Personas Reviewers' LIMIT 1;
INSERT INTO `groups` (name, rules, notes, created, modified)
    VALUES ('Reviewers: Content', 'Addons:ContentReview', '', NOW(), NOW());
INSERT INTO `groups` (name, rules, notes, created, modified)
    VALUES ('Reviewers: Add-ons', 'Addons:PostReview', '', NOW(), NOW());
INSERT INTO `groups` (name, rules, notes, created, modified)
    VALUES ('Reviewers: Moderators', 'Ratings:Moderate', '', NOW(), NOW());

-- Copy over users that were in Add-on Reviewers to Reviewers: Moderators.
SET @from_group := (
    SELECT `id` FROM `groups` WHERE `name` = 'Reviewers: Legacy');
SET @to_group := (
    SELECT `id` FROM `groups` WHERE `name` = 'Reviewers: Moderators');
INSERT INTO groups_users (group_id, user_id) (
    SELECT @to_group, user_id FROM groups_users WHERE group_id = @from_group);
