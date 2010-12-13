ALTER TABLE `reviews` DROP FOREIGN KEY `reviews_ibfk_2`;

ALTER TABLE `reviews`
    ADD CONSTRAINT `reviews_ibfk_2` FOREIGN KEY `reviews_ibfk_2` (`user_id`)
        REFERENCES `users` (`id`)
        ON DELETE CASCADE;
