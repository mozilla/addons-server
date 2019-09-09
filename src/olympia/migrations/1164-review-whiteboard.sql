ALTER TABLE `review_whiteboard`
    DROP FOREIGN KEY `addon_id_refs_id_3aa22f51`,
    ADD CONSTRAINT `review_whiteboard_addon_id_249c0a4a_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
