CREATE TABLE `personas_users` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `persona_id` int(11) unsigned NOT NULL,
    `author_id` int(11) unsigned NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

ALTER TABLE `personas_users` ADD CONSTRAINT `author_id_refs_id_author`
     FOREIGN KEY (`author_id`) REFERENCES `users` (`id`);
ALTER TABLE `personas_users` ADD CONSTRAINT `persona_id_refs_id_persona`
     FOREIGN KEY (`persona_id`) REFERENCES `personas` (`id`);
