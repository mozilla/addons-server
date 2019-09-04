ALTER TABLE `addons_addonapprovalscounter`
    DROP FOREIGN KEY addon_id_refs_id_8fcb7166,
    ADD CONSTRAINT `addons_addonapprovalscounter_addon_id_4a0a4308_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
