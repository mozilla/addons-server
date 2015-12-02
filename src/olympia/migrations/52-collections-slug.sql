-- Create a new slug column so we don't mess up remora's data model.
ALTER TABLE collections ADD COLUMN `slug` varchar(30) DEFAULT NULL;

UPDATE collections SET slug=nickname WHERE nickname IS NOT NULL;

-- There's a single collection without a created date.  WTF?
UPDATE collections SET created='2009-06-09 21:34:13' WHERE created IS NULL;
