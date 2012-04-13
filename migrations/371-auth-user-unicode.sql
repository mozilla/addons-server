-- Old value was latin1, causing bug 731639
alter table auth_user convert to character set utf8;
