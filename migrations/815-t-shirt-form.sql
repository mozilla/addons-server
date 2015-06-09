CREATE TABLE `user_t_shirt_orders` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `user_id` integer NOT NULL UNIQUE,
    `name` varchar(512) NOT NULL,
    `address1` varchar(512) NOT NULL,
    `address2` varchar(512) NOT NULL,
    `city` varchar(512) NOT NULL,
    `state` varchar(512) NOT NULL,
    `zip` varchar(32) NOT NULL,
    `country` varchar(512) NOT NULL,
    `telephone` varchar(512) NOT NULL,
    `shirt_size` varchar(3) NOT NULL,
    `shirt_style` varchar(1) NOT NULL,
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
);

INSERT INTO
    waffle_switch (name, active, created, modified, note)
VALUES
    ('t-shirt-orders', 0, NOW(), NOW(), 'Accept special edition add-ons t-shirt requests.');
