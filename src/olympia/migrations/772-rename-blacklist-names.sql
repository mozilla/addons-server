-- Rename the table to be consistent with the model name.
ALTER TABLE users_blacklistedusername RENAME TO users_blacklistedname;
-- Rename the field `username` to `name` for consistency too.
ALTER TABLE users_blacklistedname CHANGE COLUMN username name varchar(255) NOT NULL UNIQUE;
