-- Uncomment this locally if you can't create files anymore.
-- On dev/stage/prod, this isn't necessary as those columns already have a
-- default value. They will be removed entirely in a future push (issue #10977)
-- ALTER TABLE `files` MODIFY COLUMN `requires_chrome` tinyint(1) NOT NULL DEFAULT 0;
-- ALTER TABLE `files` MODIFY COLUMN `is_multi_package` tinyint(1) NOT NULL DEFAULT 0;

DELETE `users_tags_addons` FROM `users_tags_addons` INNER JOIN `tags`
    ON ( `users_tags_addons`.`tag_id` = `tags`.`id` )
    WHERE `tags`.`tag_text` = 'jetpack';

DELETE FROM `tags` WHERE `tag_text` = 'jetpack';
