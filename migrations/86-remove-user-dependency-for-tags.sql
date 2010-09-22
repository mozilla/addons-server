ALTER TABLE users_tags_addons DROP FOREIGN KEY users_tags_addons_ibfk_1;
ALTER TABLE users_tags_addons MODIFY user_id INT(11) unsigned;
