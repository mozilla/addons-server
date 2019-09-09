/* There are some old entries in download_counts where the addon has already been hard-deleted so there is no matching id in addons.
As we're adding a foreign key constraint to the table we need to first delete the invalid data or the ALTER TABLE fails.*/
DELETE FROM `download_counts` USING `download_counts`
    LEFT JOIN `addons` ON `addon_id` = `addons`.`id`
    WHERE `addons`.`id` IS NULL AND `addon_id` IS NOT NULL;

ALTER TABLE `download_counts`
    MODIFY `addon_id` int(10) unsigned NOT NULL,
    MODIFY `count` int(10) unsigned NOT NULL,
    MODIFY `date` date NOT NULL,
    ADD CONSTRAINT `download_counts_addon_id_59e6706f_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
