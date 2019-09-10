ALTER TABLE `collections`
    ADD UNIQUE KEY `name` (`name`),
    ADD UNIQUE KEY `description` (`description`);
