-- Make all the existing emails unique, so that the unique uuid constraint
-- won't fail.
UPDATE users_install SET email = CONCAT(id, '|', email);
-- Rename email to uuid.
ALTER TABLE users_install CHANGE COLUMN email uuid varchar(255) UNIQUE;
