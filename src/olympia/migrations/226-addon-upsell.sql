CREATE TABLE `addon_upsell` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `free_id` int(11) unsigned NOT NULL,
    `premium_id` int(11) unsigned NOT NULL,
    `text` int(11) unsigned NOT NULL,
    UNIQUE (`free_id`, `premium_id`)
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `addon_upsell` ADD CONSTRAINT `free_id_refs_id_upsell` FOREIGN KEY (`free_id`) REFERENCES `addons` (`id`);
ALTER TABLE `addon_upsell` ADD CONSTRAINT `premium_id_refs_id_upsell` FOREIGN KEY (`premium_id`) REFERENCES `addons` (`id`);
ALTER TABLE `addon_upsell` ADD CONSTRAINT `text_translated` FOREIGN KEY (`text`) REFERENCES `translations` (`id`);
CREATE INDEX `addon_upsell_free_id` ON `addon_upsell` (`free_id`);
CREATE INDEX `addon_upsell_premium_id` ON `addon_upsell` (`premium_id`);
