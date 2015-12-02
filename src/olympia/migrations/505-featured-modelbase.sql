ALTER TABLE zadmin_featuredapp ADD COLUMN created datetime NOT NULL;
ALTER TABLE zadmin_featuredapp ADD COLUMN modified datetime NOT NULL;

ALTER TABLE zadmin_featuredappregion ADD COLUMN created datetime NOT NULL;
ALTER TABLE zadmin_featuredappregion ADD COLUMN modified datetime NOT NULL;

ALTER TABLE zadmin_featuredappcarrier ADD COLUMN created datetime NOT NULL;
ALTER TABLE zadmin_featuredappcarrier ADD COLUMN modified datetime NOT NULL;
