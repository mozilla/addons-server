-- In addition to converting the table, also need to convert this column. See
-- bug 731639
ALTER TABLE auth_user MODIFY COLUMN username varchar(255) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL;
