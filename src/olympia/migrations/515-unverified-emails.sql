-- Add verified email flag for unverified email addresses (bug 794634)

ALTER TABLE users ADD COLUMN is_verified tinyint(1) unsigned DEFAULT 1;
