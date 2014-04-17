SET foreign_key_checks = 0;

DROP TABLE refunds;
DROP TABLE price_currency;
DROP TABLE addons_premium;
DROP TABLE inapp_products;
DROP TABLE addon_purchase;
DROP TABLE addon_payment_data;
DROP TABLE paypal_checkstatus;
ALTER TABLE stats_contributions
    DROP FOREIGN KEY price_tier_id_refs,
    DROP FOREIGN KEY user_id_refs,
    DROP COLUMN price_tier_id,
    DROP COLUMN related_id,
    DROP COLUMN user_id,
    DROP COLUMN type;
DROP TABLE prices;
SET foreign_key_checks = 1;
