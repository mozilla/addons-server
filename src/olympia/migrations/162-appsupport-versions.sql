ALTER TABLE appsupport
  ADD COLUMN `min` bigint(20) unsigned DEFAULT NULL,
  ADD COLUMN `max` bigint(20) unsigned DEFAULT NULL;

CREATE INDEX minmax_idx ON appsupport (addon_id, app_id, min, max);
