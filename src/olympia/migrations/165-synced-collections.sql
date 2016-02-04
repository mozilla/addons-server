DROP TABLE IF EXISTS `synced_collections`;
CREATE TABLE `synced_collections` (
    `id` int(11) UNSIGNED AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `addon_index` varchar(40) UNIQUE,
    `count` int(11) UNSIGNED NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

DROP TABLE IF EXISTS `synced_addons_collections`;
CREATE TABLE `synced_addons_collections` (
    `id` int(11) UNSIGNED AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `addon_id` int(11) UNSIGNED NOT NULL,
    `collection_id` int(11) UNSIGNED NOT NULL,
    UNIQUE (`addon_id`, `collection_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

ALTER TABLE `synced_addons_collections`
    ADD CONSTRAINT FOREIGN KEY (`addon_id`)
                   REFERENCES `addons` (`id`) ON DELETE CASCADE,
    ADD CONSTRAINT FOREIGN KEY (`collection_id`)
                   REFERENCES `synced_collections` (`id`) ON DELETE CASCADE;
