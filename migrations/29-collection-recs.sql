ALTER TABLE collections
    ADD COLUMN `addon_index` varchar(40) NULL,
    ADD COLUMN `recommended_collection_id` int(11) unsigned NULL,
    ADD FOREIGN KEY (`recommended_collection_id`) REFERENCES `collections` (`id`);

CREATE INDEX `collections_addon_index` ON `collections` (`addon_index`);
