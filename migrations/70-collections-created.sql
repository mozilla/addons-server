UPDATE addons_collections SET created=added WHERE created IS NULL;

ALTER TABLE collections DROP COLUMN password;
