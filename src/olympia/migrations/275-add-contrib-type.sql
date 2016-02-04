ALTER TABLE addon_purchase ADD COLUMN type int(11) unsigned NOT NULL default 1;
CREATE INDEX addon_purchase_type ON addon_purchase (type);
