ALTER TABLE `collections`
    MODIFY `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    MODIFY `name` int(10) unsigned DEFAULT NULL,
    MODIFY `defaultlocale` varchar(10) NOT NULL,
    MODIFY `collection_type` int(10) unsigned NOT NULL,
    MODIFY `description` int(10) unsigned DEFAULT NULL,
    MODIFY `listed` tinyint(1) NOT NULL,
    MODIFY `addonCount` int(10) unsigned NOT NULL,
    DROP KEY `name`,
    DROP KEY `description`,
    DROP FOREIGN KEY `collections_ibfk_4`,  /* `name` */
    DROP FOREIGN KEY `collections_ibfk_5`,  /* `description` */
    DROP FOREIGN KEY `collections_ibfk_7`,  /* `author_id` */
    ADD CONSTRAINT `collections_author_id_c9323760_fk_users_id` FOREIGN KEY (`author_id`) REFERENCES `users` (`id`),
    ADD CONSTRAINT `collections_description_64108f9e_fk_translations_id` FOREIGN KEY (`description`) REFERENCES `translations` (`id`),
    ADD CONSTRAINT `collections_name_c898e2c4_fk_translations_id` FOREIGN KEY (`name`) REFERENCES `translations` (`id`);*/

ALTER TABLE `collections`
    ADD UNIQUE KEY `name` (`name`),
    ADD UNIQUE KEY `description` (`description`);
