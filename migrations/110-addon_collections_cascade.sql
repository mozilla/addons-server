SET FOREIGN_KEY_CHECKS=0;

ALTER TABLE `addons_collections`
 DROP FOREIGN KEY `addons_collections_ibfk_1`;

ALTER TABLE `addons_collections`
 DROP FOREIGN KEY `addons_collections_ibfk_2`;

ALTER TABLE `addons_collections`
 DROP FOREIGN KEY `addons_collections_ibfk_4`;

ALTER TABLE `addons_collections` ADD CONSTRAINT `addons_collections_ibfk_1` FOREIGN KEY `addons_collections_ibfk_1` (`addon_id`)
    REFERENCES `addons` (`id`)
    ON DELETE CASCADE
    ON UPDATE RESTRICT,
 ADD CONSTRAINT `addons_collections_ibfk_2` FOREIGN KEY `addons_collections_ibfk_2` (`collection_id`)
    REFERENCES `collections` (`id`)
    ON DELETE CASCADE
    ON UPDATE RESTRICT,
 ADD CONSTRAINT `addons_collections_ibfk_4` FOREIGN KEY `addons_collections_ibfk_4` (`comments`)
    REFERENCES `translations` (`id`)
    ON DELETE SET NULL
    ON UPDATE RESTRICT;

SET FOREIGN_KEY_CHECKS=1;
