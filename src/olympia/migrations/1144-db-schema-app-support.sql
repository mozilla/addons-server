ALTER TABLE `appsupport`
    MODIFY `id` int(10) unsigned NOT NULL,
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    MODIFY `addon_id` int(10) unsigned NOT NULL,
    MODIFY `app_id` int(10) unsigned NOT NULL,
    MODIFY `min` bigint(20) DEFAULT NULL,
    MODIFY `max` bigint(20) DEFAULT NULL,
    ADD CONSTRAINT `appsupport_addon_id_a4820965_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
