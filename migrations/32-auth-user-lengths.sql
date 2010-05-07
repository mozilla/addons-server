ALTER TABLE auth_user
    CHANGE COLUMN username `username` varchar(255) NOT NULL UNIQUE,
    CHANGE COLUMN first_name `first_name` varchar(255) NOT NULL,
    CHANGE COLUMN last_name `last_name` varchar(255) NOT NULL,
    CHANGE COLUMN email `email` varchar(255) NOT NULL UNIQUE;
