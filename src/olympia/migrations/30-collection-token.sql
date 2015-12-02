DROP TABLE IF EXISTS `collections_tokens`;
CREATE TABLE `collections_tokens` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `collection_id` integer NOT NULL,
    `token` varchar(255) NOT NULL UNIQUE
)
;
ALTER TABLE `collections_tokens` ADD CONSTRAINT `collection_id_refs_id_2d03c093` FOREIGN KEY (`collection_id`) REFERENCES `collections` (`id`);
