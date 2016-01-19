DROP TABLE IF EXISTS `addon_recommendations`;

 -- collection_type 1: COLLECTION_SYNCHRONIZED
 -- collection_type 3: COLLECTION_RECOMMENDED

DELETE addons_collections FROM addons_collections
    INNER JOIN collections
    ON addons_collections.collection_id=collections.id
    WHERE collections.collection_type IN (1, 3);

DELETE collection_promos FROM collection_promos
    INNER JOIN collections
    ON collection_promos.collection_id=collections.id
    WHERE collections.collection_type IN (1, 3);

DELETE collection_subscriptions FROM collection_subscriptions
    INNER JOIN collections
    ON collection_subscriptions.collection_id=collections.id
    WHERE collections.collection_type IN (1, 3);

DELETE collections_users FROM collections_users
    INNER JOIN collections
    ON collections_users.collection_id=collections.id
    WHERE collections.collection_type IN (1, 3);

DELETE collections_votes FROM collections_votes
    INNER JOIN collections
    ON collections_votes.collection_id=collections.id
    WHERE collections.collection_type IN (1, 3);

DELETE featured_collections FROM featured_collections
    INNER JOIN collections
    ON featured_collections.collection_id=collections.id
    WHERE collections.collection_type IN (1, 3);

DELETE stats_addons_collections_counts FROM stats_addons_collections_counts
    INNER JOIN collections
    ON stats_addons_collections_counts.collection_id=collections.id
    WHERE collections.collection_type IN (1, 3);

DELETE stats_collections FROM stats_collections
    INNER JOIN collections
    ON stats_collections.collection_id=collections.id
    WHERE collections.collection_type IN (1, 3);

DELETE stats_collections_counts FROM stats_collections_counts
    INNER JOIN collections
    ON stats_collections_counts.collection_id=collections.id
    WHERE collections.collection_type IN (1, 3);

DELETE stats_collections_share_counts_totals FROM stats_collections_share_counts_totals
    INNER JOIN collections
    ON stats_collections_share_counts_totals.collection_id=collections.id
    WHERE collections.collection_type IN (1, 3);

DELETE FROM collections WHERE collection_type IN (1, 3);
DELETE FROM waffle_flag WHERE name = 'disco-pane-show-recs';
