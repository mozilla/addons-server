-- Warning, this is going to be a slow migration.
ALTER TABLE stats_contributions ADD COLUMN type int(11) unsigned NOT NULL;
ALTER TABLE stats_contributions ADD COLUMN user_id int(11) unsigned;
ALTER TABLE stats_contributions ADD COLUMN price_tier_id int(11);
ALTER TABLE stats_contributions ADD COLUMN currency varchar(3);
ALTER TABLE stats_contributions ADD COLUMN related_id int(11) unsigned;

ALTER TABLE stats_contributions ADD CONSTRAINT user_id_refs FOREIGN KEY (user_id) REFERENCES users (id);
ALTER TABLE stats_contributions ADD CONSTRAINT price_tier_id_refs FOREIGN KEY (price_tier_id) REFERENCES prices (id);
ALTER TABLE stats_contributions ADD CONSTRAINT related_id_refs FOREIGN KEY (related_id) REFERENCES stats_contributions (id);

CREATE INDEX stats_contributions_type ON stats_contributions (type);
CREATE INDEX stats_contributions_user_id ON stats_contributions (user_id);
CREATE INDEX stats_contributions_price_tier_id ON stats_contributions (price_tier_id);
CREATE INDEX stats_contributions_related ON stats_contributions (related_id);
