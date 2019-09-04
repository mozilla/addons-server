ALTER TABLE `addons_categories`
    MODIFY `addon_id` int(10) unsigned NOT NULL,
    MODIFY `category_id` int(10) unsigned NOT NULL,
    MODIFY `feature` tinyint(1) NOT NULL,
    DROP FOREIGN KEY `addons_categories_ibfk_3`,  /* addons.id */
    DROP FOREIGN KEY `addons_categories_ibfk_4`,  /* categories.id */
    ADD CONSTRAINT `addons_categories_addon_id_9d915915_fk_addons_id` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`),
    ADD CONSTRAINT `addons_categories_category_id_f4f5c093_fk_categories_id` FOREIGN KEY (`category_id`) REFERENCES `categories` (`id`);
