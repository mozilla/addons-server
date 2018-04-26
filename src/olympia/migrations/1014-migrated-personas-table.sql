-- Note: if the migration fails for you locally, remove the 'unsigned' next to version_id below.
CREATE TABLE IF NOT EXISTS `migrated_personas` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `created` datetime(6) NOT NULL,
  `modified` datetime(6) NOT NULL,
  `lightweight_theme_id` int(11) UNSIGNED NOT NULL,
  `getpersonas_id` int(11) NOT NULL,
  `static_theme_id` int(11) UNSIGNED NOT NULL,
  PRIMARY KEY (`id`),
  KEY `migrated_personas_lightweight_theme_id_fk_addons_id` (`lightweight_theme_id`),
  KEY `migrated_personas_static_theme_id_fk_addons_id` (`static_theme_id`),
  CONSTRAINT `migrated_personas_lightweight_theme_id_fk_addons_id` FOREIGN KEY (`lightweight_theme_id`) REFERENCES `addons` (`id`),
  CONSTRAINT `migrated_personas_static_theme_id_fk_addons_id` FOREIGN KEY (`static_theme_id`) REFERENCES `addons` (`id`),
  INDEX `migrated_personas_getpersonas_id` (`getpersonas_id`)
);
