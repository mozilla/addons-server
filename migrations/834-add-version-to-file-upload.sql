ALTER TABLE `file_uploads`
    ADD COLUMN `version` varchar(255),
    ADD COLUMN `addon_id` int(11);
ALTER TABLE `file_uploads`
    ADD CONSTRAINT `file_uploads_refs_addon_id`
    FOREIGN KEY `file_uploads_refs_addon_id` (`addon_id`)
    REFERENCES `addons` (`id`);
