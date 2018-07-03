DELETE FROM groups_users WHERE group_id IN (SELECT id FROM groups WHERE name = "Limited Reviewers");
DELETE FROM groups WHERE name = "Limited Reviewers";
