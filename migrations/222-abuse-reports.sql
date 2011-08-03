CREATE TABLE `abuse_reports` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `reporter_id` int(11) unsigned,
    `ip_address` varchar(255) NOT NULL,
    `addon_id` int(11) unsigned,
    `user_id` int(11) unsigned,
    `message` longtext NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8 ;
ALTER TABLE `abuse_reports` ADD CONSTRAINT `reporter_id_refs_id_12d88e23`
    FOREIGN KEY (`reporter_id`) REFERENCES `users` (`id`);
ALTER TABLE `abuse_reports` ADD CONSTRAINT `user_id_refs_id_12d88e23`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);
ALTER TABLE `abuse_reports` ADD CONSTRAINT `addon_id_refs_id_2b6ff2a7`
    FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
