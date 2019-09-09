/* There are some old entries in appsupport where the addon has already been hard-deleted so there is no matching id in addons.
As we're adding a foreign key constraint to the table we need to first delete the invalid data or the ALTER TABLE fails.*/
DELETE FROM `appsupport` USING `appsupport`
    LEFT JOIN `addons` ON `appsupport`.`addon_id`=`addons`.id`
    WHERE `addons`.`id` IS NULL AND `appsupport`.`addon_id` IS NOT NULL;

ALTER TABLE `appsupport`
    MODIFY `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    MODIFY `addon_id` int(10) unsigned NOT NULL,
    MODIFY `app_id` int(10) unsigned NOT NULL,
    MODIFY `min` bigint(20) DEFAULT NULL,
    MODIFY `max` bigint(20) DEFAULT NULL,
    ADD CONSTRAINT `appsupport_addon_id_a4820965_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
