SET foreign_key_checks = 0;
DROP TABLE IF EXISTS refunds;
DROP TABLE IF EXISTS price_currency;
DROP TABLE IF EXISTS addons_premium;
DROP TABLE IF EXISTS inapp_products;
DROP TABLE IF EXISTS addon_purchase;
DROP TABLE IF EXISTS addon_payment_data;
DROP TABLE IF EXISTS paypal_checkstatus;
ALTER TABLE stats_contributions
    DROP FOREIGN KEY related_id_refs,
    DROP FOREIGN KEY price_tier_id_refs,
    DROP FOREIGN KEY user_id_refs,
    DROP COLUMN price_tier_id,
    DROP COLUMN related_id,
    DROP COLUMN user_id,
    DROP COLUMN type;
DROP TABLE IF EXISTS prices;
SET foreign_key_checks = 1;
