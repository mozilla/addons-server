ALTER TABLE users
    CHANGE COLUMN last_login last_login datetime NOT NULL DEFAULT '1970-01-01 00:00:00';
