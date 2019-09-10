ALTER TABLE `users_tags_addons`
    DROP FOREIGN KEY `users_tags_addons_ibfk_2`,
    DROP FOREIGN KEY `users_tags_addons_ibfk_3`,
    CHANGE COLUMN `created` `created` DATETIME (6) NOT NULL,
    CHANGE COLUMN `modified` `modified` DATETIME (6) NOT NULL,
    CHANGE COLUMN `addon_id` `addon_id` INT (10) UNSIGNED NOT NULL,
    CHANGE COLUMN `tag_id` `tag_id` INT (10) UNSIGNED NOT NULL,
    ADD INDEX `users_tags_addons_tag_id_db2035d3_fk_tags_id` (`tag_id`),
    ADD INDEX `users_tags_addons_addon_id_3ca01209_fk_addons_id` (`addon_id`),
    ADD CONSTRAINT `users_tags_addons_addon_id_3ca01209_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`),
    ADD CONSTRAINT `users_tags_addons_tag_id_db2035d3_fk_tags_id` FOREIGN KEY (`tag_id`) REFERENCES `tags` (`id`);
