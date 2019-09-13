ALTER TABLE `licenses`
    MODIFY `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
    MODIFY `text` int(10) unsigned DEFAULT NULL,
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    MODIFY `name` int(10) unsigned DEFAULT NULL,
    MODIFY `builtin` int(10) unsigned NOT NULL,
    MODIFY `on_form` tinyint(1) NOT NULL,
    MODIFY `some_rights` tinyint(1) NOT NULL,
    MODIFY `creative_commons` tinyint(1) NOT NULL,
    DROP KEY `text`,
    DROP KEY `name`,
    ADD UNIQUE KEY `name` (`name`),
    ADD UNIQUE KEY `text` (`text`),
    DROP FOREIGN KEY `licenses_ibfk_1`,  /* (`text`) REFERENCES `translations` (`id`),*/
    DROP FOREIGN KEY `licenses_ibfk_2`,  /* (`name`) REFERENCES `translations` (`id`)*/
    ADD CONSTRAINT `licenses_name_0308e4d2_fk_translations_id` FOREIGN KEY (`name`) REFERENCES `translations` (`id`),
    ADD CONSTRAINT `licenses_text_1997f964_fk_translations_id` FOREIGN KEY (`text`) REFERENCES `translations` (`id`);
