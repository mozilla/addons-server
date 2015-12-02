ALTER TABLE `log_activity_addon`
 DROP FOREIGN KEY `addon_id_refs_id_5bfa17d1`;

ALTER TABLE `log_activity_addon` ADD CONSTRAINT `addon_id_refs_id_5bfa17d1` FOREIGN KEY `addon_id_refs_id_5bfa17d1` (`addon_id`)
    REFERENCES `addons` (`id`)
    ON DELETE CASCADE;

