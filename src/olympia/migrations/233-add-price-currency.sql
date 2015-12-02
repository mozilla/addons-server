CREATE TABLE `price_currency` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `currency` varchar(10) NOT NULL,
    `price` numeric(5, 2) NOT NULL,
    `tier_id` int(11) NOT NULL
)  ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `price_currency` ADD CONSTRAINT `price_currency_tier_id` FOREIGN KEY (`tier_id`) REFERENCES `prices` (`id`);
CREATE INDEX `price_currency_tier_id` ON `price_currency` (`tier_id`);
