-- Sorry :) time to make tea.
ALTER TABLE addons ADD COLUMN `app_domain` varchar(255) NULL;
CREATE INDEX `addons_609c04a9` ON `addons` (`app_domain`);
