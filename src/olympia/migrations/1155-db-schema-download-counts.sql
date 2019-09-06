ALTER TABLE `download_counts`
    MODIFY `addon_id` int(10) unsigned NOT NULL,
    MODIFY `count` int(10) unsigned NOT NULL,
    MODIFY `date` date NOT NULL,
    ADD CONSTRAINT `download_counts_addon_id_59e6706f_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
