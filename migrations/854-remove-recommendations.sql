DROP TABLE IF EXISTS `addon_recommendations`;
DELETE collection_subscriptions FROM collection_subscriptions
    INNER JOIN collections
    ON collection_subscriptions.collection_id=collections.id
    WHERE collections.collection_type IN (1, 3);
DELETE FROM collections WHERE collection_type IN (1, 3); -- COLLECTION_SYNCHRONIZED or COLLECTION_RECOMMENDED
DELETE FROM waffle_flag WHERE name = 'disco-pane-show-recs';
