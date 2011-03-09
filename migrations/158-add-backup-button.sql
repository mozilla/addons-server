ALTER TABLE addons ADD COLUMN backup_version int(11) unsigned;
ALTER TABLE addons ADD CONSTRAINT addons_ibfk_16 FOREIGN KEY (backup_version) REFERENCES versions (id) ON DELETE SET NULL;

-- Lifted from #160.
UPDATE collections SET addon_index=NULL;

-- Lifted from #161.
TRUNCATE addon_recommendations;

UPDATE collections SET recommended_collection_id=NULL;

DELETE FROM collections WHERE collection_type=3;
