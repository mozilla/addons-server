DROP TABLE IF EXISTS `synced_addons_collections`;
DROP TABLE IF EXISTS `synced_collections`;
DELETE FROM waffle_flag WHERE name = 'disco-pane-store-collections';