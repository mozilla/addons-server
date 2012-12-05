CREATE TABLE `payments_seller` (
    `id` int(11) AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `user_id` int(11) NOT NULL,
    `uuid` varchar(255) NOT NULL UNIQUE,
    `resource_uri` varchar(255) NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci
;
ALTER TABLE `payments_seller` ADD CONSTRAINT `user_id_refs_id_29692a2a` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);
CREATE INDEX `payments_seller_fbfc09f1` ON `payments_seller` (`user_id`);

CREATE TABLE `payment_accounts` (
    `id` int(11) AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `user_id` int(11) NOT NULL,
    `name` varchar(64) NOT NULL,
    `seller_uri` varchar(255) NOT NULL UNIQUE,
    `uri` varchar(255) NOT NULL UNIQUE,
    `inactive` bool NOT NULL,
    UNIQUE (`user_id`, `uri`)
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci
;
ALTER TABLE `payment_accounts` ADD CONSTRAINT `user_id_refs_id_4f9c3df5` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);
CREATE INDEX `payment_accounts_fbfc09f1` ON `payment_accounts` (`user_id`);

CREATE TABLE `addon_payment_account` (
    `id` int(11) AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `addon_id` int(11) NOT NULL UNIQUE,
    `provider` varchar(8) NOT NULL,
    `account_uri` varchar(255) NOT NULL,
    `product_uri` varchar(255) NOT NULL UNIQUE,
    `set_price` numeric(10, 2) NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci
;
ALTER TABLE `addon_payment_account` ADD CONSTRAINT `addon_id_refs_id_e46b699a` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
