ALTER TABLE prices CHANGE COLUMN price price decimal(10, 2) NOT NULL;
ALTER TABLE price_currency CHANGE COLUMN price price decimal(10, 2) NOT NULL;
