ALTER TABLE addons ADD COLUMN premium_type tinyint(1) unsigned NOT NULL DEFAULT 0;
CREATE INDEX premium_type_idx ON addons (premium_type);
