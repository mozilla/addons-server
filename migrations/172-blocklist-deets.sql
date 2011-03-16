DROP TABLE IF EXISTS `bldetails`;
CREATE TABLE `bldetails` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `name` varchar(255) NOT NULL,
    `why` longtext NOT NULL,
    `who` longtext NOT NULL,
    `bug` varchar(200) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

ALTER TABLE blitems
  ADD COLUMN `details_id` integer UNIQUE,
  ADD CONSTRAINT FOREIGN KEY (`details_id`) REFERENCES `bldetails` (`id`);

ALTER TABLE blplugins
  ADD COLUMN `details_id` integer UNIQUE,
  ADD CONSTRAINT FOREIGN KEY (`details_id`) REFERENCES `bldetails` (`id`);

ALTER TABLE blgfxdrivers
  ADD COLUMN `details_id` integer UNIQUE,
  ADD CONSTRAINT FOREIGN KEY (`details_id`) REFERENCES `bldetails` (`id`);

UPDATE blitems SET created=NOW() WHERE created IS NULL;
UPDATE blplugins SET created=NOW() WHERE created IS NULL;
UPDATE blgfxdrivers SET created=NOW() WHERE created IS NULL;
