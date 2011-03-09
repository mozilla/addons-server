TRUNCATE addon_recommendations;

UPDATE collections SET recommended_collection_id=NULL;

DELETE FROM collections WHERE collection_type=3;
