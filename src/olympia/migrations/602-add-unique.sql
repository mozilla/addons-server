TRUNCATE payment_assets;
ALTER TABLE payment_assets MODIFY COLUMN `ext_url` varchar(255) NOT NULL UNIQUE;
