ALTER TABLE reviews
    ADD COLUMN addon_id int(11) unsigned NULL,
    ADD FOREIGN KEY (addon_id) REFERENCES addons (id),
    CHANGE COLUMN version_id version_id int(11) unsigned NULL;

UPDATE reviews SET addon_id=
  (SELECT addon_id FROM versions WHERE id=version_id);
