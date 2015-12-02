ALTER TABLE addon_inapp ADD COLUMN key_timestamp varchar(10);
CREATE INDEX addon_inapp_667f58ba ON addon_inapp (key_timestamp);
-- The date here needs to correspond to what we put in the settings file.
UPDATE addon_inapp SET key_timestamp = '2012-05-09' WHERE private_key IS NOT NULL;
