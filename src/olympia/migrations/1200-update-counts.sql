DELETE FROM `update_counts` USING `update_counts`
    LEFT JOIN `addons` ON `addon_id` = `addons`.`id`
    WHERE `addons`.`id` IS NULL AND `addon_id` IS NOT NULL;

ALTER TABLE `update_counts`
    CHANGE COLUMN `addon_id` `addon_id` INT (10) UNSIGNED NOT NULL,
    CHANGE COLUMN `count` `count` INT (10) UNSIGNED NOT NULL,
    CHANGE COLUMN `date` `date` DATE NOT NULL,
    CHANGE COLUMN `id` `id` INT (10) UNSIGNED NOT NULL AUTO_INCREMENT,
    CHANGE COLUMN `locale` `locale` LONGTEXT,
    CHANGE COLUMN `os` `os` LONGTEXT,
    CHANGE COLUMN `status` `status` LONGTEXT,
    CHANGE COLUMN `version` `version` LONGTEXT,
    ADD CONSTRAINT `update_counts_addon_id_3ae4e81f_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);    
