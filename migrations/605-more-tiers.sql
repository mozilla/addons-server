ALTER TABLE price_currency ADD COLUMN carrier int(11) UNSIGNED NOT NULL;
ALTER TABLE price_currency ADD COLUMN provider int(11) UNSIGNED NOT NULL;
ALTER TABLE price_currency ADD COLUMN region int(11) UNSIGNED NOT NULL;
ALTER TABLE price_currency DROP INDEX tier_id;
ALTER TABLE price_currency ADD UNIQUE (`tier_id`, `currency`, `carrier`, `region`);

UPDATE price_currency SET provider = 1;
