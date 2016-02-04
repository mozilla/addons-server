ALTER TABLE prices ADD COLUMN method int(11) UNSIGNED NOT NULL;
/* Make everything all payment methods */
UPDATE prices SET method = 2;
/* Make micro payment tiers < 0.99 carrier only */
UPDATE prices SET method = 0 WHERE price < '0.99' and price > '0.00';
