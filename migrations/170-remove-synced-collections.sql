-- Clear out all the foreign keys since there's no CASCADE.
DELETE st FROM stats_addons_collections_counts st
    INNER JOIN collections ON (
        st.collection_id=collections.id AND
        collection_type IN (1, 3) AND
        author_id IS NULL);

DELETE st FROM stats_collections_counts st
    INNER JOIN collections ON (
        st.collection_id=collections.id AND
        collection_type IN (1, 3) AND
        author_id IS NULL);

UPDATE collections SET recommended_collection_id = NULL;

-- Remove synced and recommended collections;
DELETE FROM collections
    WHERE collection_type IN (1, 3) AND author_id IS NULL;

ALTER TABLE collections
    DROP FOREIGN KEY collections_ibfk_6,
    DROP COLUMN recommended_collection_id;

DROP TABLE collections_tokens;
