ALTER TABLE `frozen_addons`
    MODIFY `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
    MODIFY `addon_id` int(10) unsigned NOT NULL,
    DROP KEY `addon_id`,
    ADD KEY `frozen_addons_addon_id_ee7af26e_fk_addons_id` (`addon_id`),
    ADD CONSTRAINT `frozen_addons_addon_id_ee7af26e_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
