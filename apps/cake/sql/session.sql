-- putting this in session.sql since the cake backend has sha512 hashes which 
-- don't fit into the 128byte varchar field for auth_user

ALTER TABLE auth_user MODIFY `password` varchar(255) NOT NULL
