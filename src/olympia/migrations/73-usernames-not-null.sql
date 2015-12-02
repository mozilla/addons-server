-- Originally from migration 66

ALTER TABLE users CHANGE COLUMN `username` `username` varchar(255) NOT NULL;

