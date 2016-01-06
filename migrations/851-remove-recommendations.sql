DROP TABLE IF EXISTS `addon_recommendations`;
DELETE FROM collections WHERE collection_type IN (1, 3); -- COLLECTION_SYNCHRONIZED or COLLECTION_RECOMMENDED
DELETE FROM waffle_flag WHERE name = 'disco-pane-show-recs';
