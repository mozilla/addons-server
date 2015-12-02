CREATE TABLE `charities` (
    `id` int(11) UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `name` varchar(255) NOT NULL,
    `url` varchar(200) NOT NULL,
    `paypal` varchar(255) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

ALTER TABLE addons
    ADD COLUMN `charity_id` int(11) UNSIGNED,
    ADD CONSTRAINT FOREIGN KEY (`charity_id`) REFERENCES `charities` (`id`);

INSERT INTO `charities` VALUE (1, NOW(), NOW(),
                               'Mozilla Foundation', 'http://www.mozilla.org/',
                                'accounting@mozilla.org');
