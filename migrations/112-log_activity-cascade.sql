-- If these FKs don't exist, run them manually and use:
-- schematic migrations/ -u 112

-- ALTER TABLE `log_activity_addon`
--    DROP FOREIGN KEY `activity_log_id_refs_id_9c20a926`;

ALTER TABLE `log_activity_addon` ADD CONSTRAINT `activity_log_id_refs_id_9c20a926` FOREIGN KEY `activity_log_id_refs_id_9c20a926` (`addon_id`)
    REFERENCES `log_activity` (`id`)
    ON DELETE CASCADE;

ALTER TABLE `log_activity_user`
 DROP FOREIGN KEY `activity_log_id_refs_id_4f8d99d4`;

ALTER TABLE `log_activity_user` ADD CONSTRAINT `activity_log_id_refs_id_9c20a926` FOREIGN KEY `activity_log_id_refs_id_4f8d99d4` (`addon_id`)
    REFERENCES `log_activity` (`id`)
    ON DELETE CASCADE;


