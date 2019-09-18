/* There are some old entries in previews which have a caption that point to non-existant translations, need to NULL the captions them to add the missing constraint */
UPDATE `previews`
    LEFT JOIN `translations` ON `previews`.`caption` = `translations`.`id`
    SET `previews`.`caption`=NULL
    WHERE `translations`.`id` IS NULL AND `previews`.`caption` IS NOT NULL;

ALTER TABLE `previews`
    DROP FOREIGN KEY `previews_ibfk_1`,
    DROP FOREIGN KEY `previews_ibfk_2`,
    DROP INDEX `previews_ibfk_2`,
    CHANGE COLUMN `modified` `modified` DATETIME (6) NOT NULL,
    CHANGE COLUMN `id` `id` INT (10) UNSIGNED NOT NULL AUTO_INCREMENT,
    CHANGE COLUMN `addon_id` `addon_id` INT (10) UNSIGNED NOT NULL,
    CHANGE COLUMN `caption` `caption` INT (10) UNSIGNED DEFAULT NULL,
    CHANGE COLUMN `position` `position` INT (11) NOT NULL,
    CHANGE COLUMN `created` `created` DATETIME (6) NOT NULL,
    ADD INDEX `previews_caption_f5d9791a_fk_translations_id` (`caption`),
    ADD INDEX `previews_addon_id_320f2325_fk_addons_id` (`addon_id`),
    ADD UNIQUE INDEX `caption` (`caption`),
    ADD CONSTRAINT `previews_addon_id_320f2325_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`),
    ADD CONSTRAINT `previews_caption_f5d9791a_fk_translations_id` FOREIGN KEY (`caption`) REFERENCES `translations` (`id`);
