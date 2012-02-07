CREATE TABLE `devicetypes` (
    `id` int(11) UNSIGNED NOT NULL AUTO_INCREMENT,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `name` int(11) UNSIGNED DEFAULT NULL,
    `class_name` varchar(100) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8 COLLATE utf8_general_ci;


CREATE TABLE `addons_devicetypes` (
    `id` int(11) UNSIGNED NOT NULL AUTO_INCREMENT,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `addon_id` int(11) UNSIGNED NOT NULL,
    `device_type_id` int(11) UNSIGNED NOT NULL,
    PRIMARY KEY (`id`),
    KEY `device_type_id_refs_id_4d64c634` (`device_type_id`),
    CONSTRAINT `device_type_id_refs_id_4d64c634`
        FOREIGN KEY (`device_type_id`) REFERENCES `devicetypes` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8
COLLATE utf8_general_ci;


UPDATE translations_seq SET id = LAST_INSERT_ID(id + 1);
SELECT LAST_INSERT_ID() FROM translations_seq INTO @desktop;
INSERT INTO translations (id, locale, localized_string)
    VALUES ((SELECT @desktop), 'en-US', 'Desktop');

UPDATE translations_seq SET id = LAST_INSERT_ID(id + 1);
SELECT LAST_INSERT_ID() FROM translations_seq INTO @mobile;
INSERT INTO translations (id, locale, localized_string)
    VALUES ((SELECT @mobile), 'en-US', 'Mobile');

UPDATE translations_seq SET id = LAST_INSERT_ID(id + 1);
SELECT LAST_INSERT_ID() FROM translations_seq INTO @tablet;
INSERT INTO translations (id, locale, localized_string)
    VALUES ((SELECT @tablet), 'en-US', 'Tablet');


INSERT INTO `devicetypes` (id, name, class_name)
    VALUES (1, @desktop, 'desktop'),
           (2, @mobile, 'mobile'),
           (3, @tablet, 'tablet');
