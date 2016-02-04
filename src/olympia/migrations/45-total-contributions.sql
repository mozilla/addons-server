ALTER TABLE addons
    ADD COLUMN total_contributions varchar(10) DEFAULT '0.00'
        AFTER suggested_amount;

-- ~48s
