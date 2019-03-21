DELETE `users_tags_addons` FROM `users_tags_addons` INNER JOIN `tags`
    ON ( `users_tags_addons`.`tag_id` = `tags`.`id` )
    WHERE `tags`.`tag_text` = 'firefox57';

DELETE FROM `tags` WHERE `tag_text` = 'firefox57';
