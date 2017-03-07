DROP TABLE IF EXISTS `webext_permission_descriptions`;
-- Note: if the migration fails for you locally, remove the 'unsigned' next to description below.
CREATE TABLE `webext_permission_descriptions` (
    `id` int(11) AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `name` char(255) NOT NULL UNIQUE,
    `description` int(11) unsigned NOT NULL
) DEFAULT CHARSET=utf8;

ALTER TABLE `webext_permission_descriptions`
  ADD CONSTRAINT `webext_permission_descriptions_translation_id`
  FOREIGN KEY (`description`) REFERENCES `translations` (`id`);
