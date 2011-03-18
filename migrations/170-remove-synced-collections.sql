-- Remove synced and recommended collections;
DELETE FROM collections
    WHERE collection_type IN (1, 3) AND author_id IS NULL;

ALTER TABLE collections
    DROP FOREIGN KEY collections_ibfk_6,
    DROP COLUMN recommended_collection_id;

DROP TABLE collections_tokens;
