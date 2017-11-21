ALTER TABLE `addons`
    DROP FOREIGN KEY `addons_ibfk_11`,
    DROP FOREIGN KEY `addons_ibfk_12`,
    DROP FOREIGN KEY `addons_ibfk_13`,
    DROP FOREIGN KEY `addons_ibfk_15`;

ALTER TABLE `addons`    
    DROP COLUMN `the_reason`,
    DROP COLUMN `the_future`,
    DROP COLUMN `wants_contributions`,
    DROP COLUMN `paypal_id`,
    DROP COLUMN `charity_id`,
    DROP COLUMN `suggested_amount`,
    DROP COLUMN `annoying`,
    DROP COLUMN `enable_thankyou`,
    DROP COLUMN `thankyou_note`;
