CREATE TABLE `version_previews` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `created` datetime(6) NOT NULL,
  `modified` datetime(6) NOT NULL,
  `version_id` int(11) NOT NULL,
  `position` int(11) NOT NULL,
  `sizes` longtext NOT NULL,
  PRIMARY KEY (`id`),
  KEY `version_previews_version_id_fk_versions_id` (`version_id`),
  CONSTRAINT `version_previews_version_id_fk_versions_id` FOREIGN KEY (`version_id`) REFERENCES `versions` (`id`)
);
CREATE INDEX versionid_position_created ON version_previews(version_id DESC, position, created);
