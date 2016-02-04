ALTER TABLE users
    ADD COLUMN last_login datetime DEFAULT NULL,
    DROP FOREIGN KEY user_id_refs_id_eb1f4611,
    DROP COLUMN user_id;

UPDATE users SET last_login = NOW();



