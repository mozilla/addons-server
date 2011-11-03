ALTER TABLE addon_purchase DROP COLUMN receipt;
ALTER TABLE users_install ADD COLUMN receipt longtext NOT NULL;
