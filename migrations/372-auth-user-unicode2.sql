-- In addition to converting the table, also need to convert this column. See
-- bug 731639

-- Set each username to a random value first. They were corrupted anyway and are not used
-- anywhere. The original value is available in users.
update auth_user set username = UUID();
ALTER TABLE auth_user MODIFY COLUMN username varchar(255) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL;
