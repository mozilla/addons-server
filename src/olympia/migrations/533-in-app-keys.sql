CREATE TABLE `user_inapp_keys` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `solitude_seller_id` int(11) unsigned NOT NULL,
    `seller_product_pk` int(11) unsigned NOT NULL UNIQUE,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
ALTER TABLE `user_inapp_keys` ADD CONSTRAINT `solitude_seller_id_refs_id_cd630821`
    FOREIGN KEY (`solitude_seller_id`) REFERENCES `payments_seller` (`id`);
CREATE INDEX `user_inapp_keys_613b0f94` ON `user_inapp_keys` (`solitude_seller_id`);

INSERT INTO waffle_switch_mkt (name, active, created, modified, note)
    VALUES ('in-app-sandbox', 0, NOW(), NOW(),
            'Enable the in-app payment sandbox');
