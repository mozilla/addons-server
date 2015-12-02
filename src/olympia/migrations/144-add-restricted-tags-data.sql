insert into tags (tag_text, blacklisted, restricted) values ('restartless', 0, 1) on duplicate key update restricted = 1;
insert into tags (tag_text, blacklisted, restricted) values ('jetpack', 0, 1) on duplicate key update restricted = 1;
