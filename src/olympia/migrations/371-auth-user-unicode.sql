-- Old value was latin1, causing bug 731639

-- Set each username to a random value first. They were corrupted anyway and are not used
-- anywhere. The original value is available in users.
update auth_user set username = UUID();
alter table auth_user convert to character set utf8 COLLATE utf8_general_ci;
