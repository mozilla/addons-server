ALTER TABLE `addons_collections`
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY  `modified` datetime(6) NOT NULL,
    MODIFY `addon_id` int(10) unsigned NOT NULL,
    MODIFY `collection_id` int(10) unsigned NOT NULL,
    MODIFY `comments` int(10) unsigned DEFAULT NULL,
    MODIFY `ordering` int(10) unsigned NOT NULL,
    DROP `added`,
    DROP `category`,
    DROP `downloads`,
    DROP FOREIGN KEY `addons_collections_ibfk_1`,  /* addons.id */
    DROP FOREIGN KEY `addons_collections_ibfk_2`,  /* collections.id */
    DROP FOREIGN KEY `addons_collections_ibfk_3`,  /* users.id */
    DROP FOREIGN KEY `addons_collections_ibfk_4`,  /* comments>translations.id */
    DROP KEY `comments`,
    ADD CONSTRAINT `addons_collections_addon_id_bbc33022_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`),
    ADD CONSTRAINT `addons_collections_collection_id_68098c79_fk_collections_id` FOREIGN KEY (`collection_id`) REFERENCES `collections` (`id`),
    ADD CONSTRAINT `addons_collections_user_id_f042641b_fk_users_id` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`),
    ADD CONSTRAINT `addons_collections_comments_3640122d_fk_translations_id` FOREIGN KEY (`comments`) REFERENCES `translations` (`id`),
    ADD UNIQUE KEY `comments` (`comments`);
