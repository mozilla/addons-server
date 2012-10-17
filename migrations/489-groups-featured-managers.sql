-- Add Featured Managers group.
INSERT INTO groups (name, rules, notes, created, modified) VALUES
  ('Feature Managers', 'FeaturedApps:View,FeaturedApps:Edit', 'For users to manage only featured apps.', NOW(), NOW());
-- Add FeaturedApps:% to Staff.
UPDATE groups SET rules=CONCAT(rules, ',FeaturedApps:View,FeaturedApps:Edit') WHERE name='Staff';
