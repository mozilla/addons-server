CREATE TABLE `addon_inapp_image` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `config_id` int(11) unsigned NOT NULL,
    `image_url` varchar(255) NOT NULL,
    `image_format` varchar(4) NOT NULL,
    `valid` bool NOT NULL,
    `processed` bool NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `addon_inapp_image`
    ADD CONSTRAINT `config_id_refs_inapp_product`
    FOREIGN KEY (`config_id`) REFERENCES `addon_inapp` (`id`)
    ON DELETE CASCADE;
CREATE INDEX `addon_inapp_image_config_id`
    ON `addon_inapp_image` (`config_id`);
CREATE INDEX `addon_inapp_image_url`
    ON `addon_inapp_image` (`image_url`);
CREATE INDEX `addon_inapp_image_valid`
    ON `addon_inapp_image` (`valid`);
CREATE INDEX `addon_inapp_image_processed`
    ON `addon_inapp_image` (`processed`);
