--
-- Bug 1142227 - Add support for OneCRL certificate blocklisting to AMO
--

DROP TABLE IF EXISTS `blissuercert`;

CREATE TABLE `blissuercert` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `issuer` longtext NOT NULL,
    `serial` varchar(255) NOT NULL,
    `details_id` integer NOT NULL UNIQUE
) ENGINE=InnoDB AUTO_INCREMENT=10 DEFAULT CHARSET=utf8;

ALTER TABLE `blissuercert` ADD CONSTRAINT FOREIGN KEY (`details_id`) REFERENCES `bldetails` (`id`);
