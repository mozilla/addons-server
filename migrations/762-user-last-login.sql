ALTER TABLE users
    CHANGE COLUMN last_login last_login datetime NOT NULL DEFAULT '0000-00-00 00:00:00';
