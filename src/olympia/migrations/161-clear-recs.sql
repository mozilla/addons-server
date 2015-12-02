TRUNCATE addon_recommendations;

ALTER TABLE addons_collections
    DROP FOREIGN KEY addons_collections_ibfk_1,
    DROP FOREIGN KEY addons_collections_ibfk_2;

ALTER TABLE addons_collections
  ADD CONSTRAINT `addons_collections_ibfk_1` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`) ON DELETE CASCADE,
  ADD CONSTRAINT `addons_collections_ibfk_2` FOREIGN KEY (`collection_id`) REFERENCES `collections` (`id`) ON DELETE CASCADE;

UPDATE collections SET recommended_collection_id=NULL;

DELETE FROM collections WHERE collection_type=3;
