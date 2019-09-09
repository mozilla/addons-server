ALTER TABLE `migrated_personas`
    DROP FOREIGN KEY `migrated_personas_static_theme_id_fk_addons_id`,
    DROP INDEX `migrated_personas_lightweight_theme_id_fk_addons_id`,
    CHANGE COLUMN `lightweight_theme_id` `lightweight_theme_id` INT (10) UNSIGNED NOT NULL,
    CHANGE COLUMN `getpersonas_id` `getpersonas_id` INT (10) UNSIGNED NOT NULL,
    CHANGE COLUMN `static_theme_id` `static_theme_id` INT (10) UNSIGNED NOT NULL,
    ADD UNIQUE INDEX `static_theme_id` (`static_theme_id`),
    ADD INDEX `migrated_personas_static_theme_id_6f4985a7_fk_addons_id` (`static_theme_id`),
    ADD CONSTRAINT `migrated_personas_static_theme_id_6f4985a7_fk_addons_id` FOREIGN KEY (`static_theme_id`) REFERENCES `addons` (`id`);
