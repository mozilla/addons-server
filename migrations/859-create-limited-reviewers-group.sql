-- Make Limited Reviewers group.
INSERT INTO groups (name, rules, notes, created, modified) VALUES
  ('Limited Reviewers', 'Addons:DelayedReviews', 'Hide recently added add-on reviews', NOW(), NOW());
