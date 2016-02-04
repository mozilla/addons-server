-- Make No Incentives group.
INSERT INTO groups (id, name, rules, notes, created, modified) VALUES
  (50066, 'No Reviewer Incentives', 'None:None', 'Reviewers who should not be included in incentives tables', NOW(), NOW());
