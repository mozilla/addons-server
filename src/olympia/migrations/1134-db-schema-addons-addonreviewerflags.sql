ALTER TABLE `addons_addonreviewerflags`
    MODIFY `auto_approval_disabled` tinyint(1) NOT NULL,
    MODIFY `notified_about_expiring_info_request` tinyint(1) NOT NULL,
    DROP FOREIGN KEY `addon_id_refs_id_7a280313`,
    ADD CONSTRAINT `addons_addonreviewerflags_addon_id_d8b2a376_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
