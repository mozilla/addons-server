ALTER TABLE `migrated_personas`
    DROP FOREIGN KEY `migrated_personas_lightweight_theme_id_fk_addons_id`;
/* If the above fails locally, try one of the following instead:
ALTER TABLE `migrated_personas`
    DROP FOREIGN KEY `lightweight_theme_id`;

ALTER TABLE `migrated_personas`
    DROP FOREIGN KEY `migrated_personas_lightweight_theme_id_d30845ab_fk_addons_id`;
*/
