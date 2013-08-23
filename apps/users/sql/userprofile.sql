-- Tweaking auth_user from 128 chars to fit sha512 password hashes.
ALTER TABLE auth_user MODIFY `password` varchar(255) NOT NULL;

-- Add constraints present in zamboni db.
ALTER TABLE auth_user ADD UNIQUE KEY `username_2` (`username`);
ALTER TABLE auth_user ADD UNIQUE KEY `email` (`email`);
