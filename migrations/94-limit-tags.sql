ALTER TABLE users_tags_addons DROP FOREIGN KEY users_tags_addons_ibfk_1;
ALTER TABLE users_tags_addons DROP INDEX user_id;
ALTER IGNORE TABLE users_tags_addons ADD UNIQUE index(tag_id, addon_id);
