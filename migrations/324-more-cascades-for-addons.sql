ALTER TABLE `addon_upsell` DROP FOREIGN KEY `free_id_refs_id_upsell`;
ALTER TABLE `addon_upsell` ADD CONSTRAINT `free_id_refs_id_upsell`
    FOREIGN KEY (`free_id`) REFERENCES `addons` (`id`) ON DELETE CASCADE;
ALTER TABLE `addon_upsell` DROP FOREIGN KEY `premium_id_refs_id_upsell`;
ALTER TABLE `addon_upsell` ADD CONSTRAINT `premium_id_refs_id_upsell`
    FOREIGN KEY (`premium_id`) REFERENCES `addons` (`id`) ON DELETE CASCADE;
ALTER TABLE `addon_upsell` DROP FOREIGN KEY `text_translated`;
ALTER TABLE `addon_upsell` ADD CONSTRAINT `text_translated`
    FOREIGN KEY (`text`) REFERENCES `translations` (`id`) ON DELETE CASCADE;

ALTER TABLE `addon_payment_data` DROP FOREIGN KEY `addon_id_refs_id_addon`;
ALTER TABLE `addon_payment_data` ADD CONSTRAINT `addon_id_refs_id_addon`
    FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`) ON DELETE CASCADE;
