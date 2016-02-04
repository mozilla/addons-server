-- Too complicated to fix, let's start over.
DELETE FROM addon_payment_account;
DELETE FROM payment_accounts;
DELETE FROM payments_seller;

ALTER TABLE payment_accounts
    ADD COLUMN `solitude_seller_id` int(11) unsigned NOT NULL;
ALTER TABLE `payment_accounts`
    ADD CONSTRAINT `solitude_seller_id_refs_id_e68bc3b0`
    FOREIGN KEY (`solitude_seller_id`) REFERENCES `payments_seller` (`id`);

ALTER TABLE addon_payment_account
    ADD COLUMN `payment_account_id` int(11) unsigned NOT NULL;
ALTER TABLE `addon_payment_account`
    ADD CONSTRAINT `payment_account_id_refs_id_af3e880c`
    FOREIGN KEY (`payment_account_id`) REFERENCES `payment_accounts` (`id`);

CREATE INDEX `payment_accounts_613b0f94` ON `payment_accounts` (`solitude_seller_id`);
CREATE INDEX `addon_payment_account_3ce7b59d` ON `addon_payment_account` (`payment_account_id`);
