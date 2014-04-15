DROP TABLE prices;
DROP TABLE price_currency;
DROP TABLE addon_purchase;
DROP TABLE addons_premium;
DROP TABLE refunds;
DROP TABLE addon_payment_data;
DROP TABLE paypal_checkstatus;

ALTER TABLE stats_contributions
    DROP COLUMN user,
    DROP COLUMN type,
    DROP COLUMN price_tier,
    DROP COLUMN related;
