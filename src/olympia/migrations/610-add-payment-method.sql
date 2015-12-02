ALTER TABLE price_currency ADD COLUMN method int(11) UNSIGNED NOT NULL;
UPDATE price_currency SET method = 2;
ALTER TABLE price_currency DROP INDEX tier_id;
ALTER TABLE price_currency ADD UNIQUE
    (`tier_id`, `currency`, `carrier`, `region`, `provider`);
