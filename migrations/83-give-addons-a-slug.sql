-- This should not default to null (and be UNIQUE) after zamboni takes over all the creation of add-ons
ALTER TABLE addons ADD COLUMN `slug` varchar(30) DEFAULT NULL AFTER `name`, ADD UNIQUE(`slug`);
