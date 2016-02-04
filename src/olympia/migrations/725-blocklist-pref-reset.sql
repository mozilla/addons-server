CREATE TABLE `blitemprefs` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `blitem_id` int(11) unsigned NOT NULL,
    `pref` varchar(255) NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;
ALTER TABLE `blitemprefs`
    ADD CONSTRAINT `blitem_id_refs_id_9e548741`
    FOREIGN KEY (`blitem_id`) REFERENCES `blitems` (`id`)
    ON DELETE CASCADE;
