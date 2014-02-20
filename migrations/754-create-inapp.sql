CREATE TABLE `inapp_products` (
    `id` int(11) UNSIGNED AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `webapp_id` int(11) UNSIGNED NOT NULL,
    `price_id` int(11) NOT NULL,
    `name` int(11) UNSIGNED UNIQUE NOT NULL,
    `logo_url` varchar(1024)
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `inapp_products` ADD CONSTRAINT `inapp_products_webapp_id` FOREIGN KEY (`webapp_id`) REFERENCES `addons` (`id`);
ALTER TABLE `inapp_products` ADD CONSTRAINT `inapp_products_price_id` FOREIGN KEY (`price_id`) REFERENCES `prices` (`id`);
ALTER TABLE `inapp_products` ADD CONSTRAINT `inapp_products_name_translation_id` FOREIGN KEY (`name`) REFERENCES `translations` (`id`);
