DROP TABLE IF EXISTS `featured_collections`;
CREATE TABLE `featured_collections` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `application_id` int(11) unsigned NOT NULL,
    `collection_id` int(11) unsigned NOT NULL,
    `locale` varchar(10)
);

ALTER TABLE `featured_collections`
    ADD CONSTRAINT FOREIGN KEY (`application_id`)
    REFERENCES `applications` (`id`);
ALTER TABLE `featured_collections`
    ADD CONSTRAINT FOREIGN KEY (`collection_id`)
    REFERENCES `collections` (`id`);

CREATE INDEX `application_id_idx` ON `featured_collections` (`application_id`);
CREATE INDEX `collection_id_idx` ON `featured_collections` (`collection_id`);
