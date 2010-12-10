SET FOREIGN_KEY_CHECKS=0;

ALTER TABLE `collections` DROP FOREIGN KEY `collections_ibfk_7`;

ALTER TABLE `collections` ADD CONSTRAINT `collections_ibfk_7`
    FOREIGN KEY `collections_ibfk_7` (`author_id`)
    REFERENCES `users` (`id`)
    ON DELETE CASCADE;

SET FOREIGN_KEY_CHECKS=1;
