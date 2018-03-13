-- Note: if the migration fails for you locally, remove the 'unsigned' next to version_id below.
CREATE TABLE `version_previews` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `created` datetime(6) NOT NULL,
  `modified` datetime(6) NOT NULL,
  `version_id` int(11) UNSIGNED NOT NULL,
  `sizes` longtext NOT NULL,
  PRIMARY KEY (`id`),
  KEY `version_previews_version_id_fk_versions_id` (`version_id`),
  CONSTRAINT `version_previews_version_id_fk_versions_id` FOREIGN KEY (`version_id`) REFERENCES `versions` (`id`)
);
