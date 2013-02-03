-- Tweaking auth_user from 128 chars to fit sha512 password hashes.
ALTER TABLE auth_user MODIFY `password` varchar(255) NOT NULL
