ALTER TABLE `addons` ADD COLUMN `mozilla_contact` varchar(75) NOT NULL;
-- Permissions changes.
UPDATE `groups` SET rules=CONCAT(rules, ',Apps:Configure') WHERE name='Staff';
UPDATE `groups` SET rules=CONCAT(rules, ',Apps:Configure') WHERE name='Support Staff';
UPDATE `groups` SET rules=CONCAT(rules, ',Apps:ViewConfiguration') WHERE name='Developers';
