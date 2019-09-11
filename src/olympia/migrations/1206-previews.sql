ALTER TABLE `previews`
    DROP INDEX `previews_caption_f5d9791a_fk_translations_id` (`caption`),
    DROP INDEX `previews_addon_id_320f2325_fk_addons_id` (`addon_id`);
