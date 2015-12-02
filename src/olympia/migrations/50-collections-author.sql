ALTER TABLE collections
    ADD COLUMN `author_id` int(11) UNSIGNED,
    ADD CONSTRAINT FOREIGN KEY (`author_id`) REFERENCES `users` (`id`);
