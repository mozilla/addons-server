CREATE TABLE `addon_purchase` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `addon_id` int(11) unsigned NOT NULL,
    `user_id` int(11) unsigned NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `addon_purchase` ADD CONSTRAINT `addon_id_refs_addon_purchase` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
ALTER TABLE `addon_purchase` ADD CONSTRAINT `user_id_refs_addon_purchase` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

CREATE INDEX `addon_purchase_addon_id_idx` ON `addon_purchase` (`addon_id`);
CREATE INDEX `addon_purchase_user_id_idx` ON `addon_purchase` (`user_id`);
