ALTER TABLE `featured_collections`
    MODIFY `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    MODIFY `application_id` int(10) unsigned NOT NULL,
    MODIFY `collection_id` int(10) unsigned NOT NULL,
    DROP KEY `collection_id_idx`,  /* (`collection_id`)*/
    ADD KEY `featured_collections_collection_id_ee8573f8_fk_collections_id` (`collection_id`),
    ADD CONSTRAINT `featured_collections_collection_id_ee8573f8_fk_collections_id` FOREIGN KEY (`collection_id`) REFERENCES `collections` (`id`);
