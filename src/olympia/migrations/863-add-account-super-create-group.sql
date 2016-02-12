-- Make a group for those who can use the AccountSuperCreate API.
INSERT INTO groups (name, rules, notes, created, modified) VALUES
  ('Account Super Creators', 'Accounts:SuperCreate',
   'These users gain access to the accounts API to super-create users. This was originally intended for automated QA tests.',
   NOW(), NOW());
