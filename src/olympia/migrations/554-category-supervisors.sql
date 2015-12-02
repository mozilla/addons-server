CREATE TABLE `categories_supervisors` (
    `id` INT(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `category_id` INT(11) unsigned NOT NULL,
    `user_id` INT(11) unsigned NOT NULL
) ENGINE=InnoDB AUTO_INCREMENT=10 DEFAULT CHARSET=utf8;
ALTER TABLE `categories_supervisors` ADD CONSTRAINT `category_id_refs_id_882d0587` FOREIGN KEY (`category_id`) REFERENCES `categories` (`id`);
ALTER TABLE `categories_supervisors` ADD CONSTRAINT `user_id_refs_id_8ddff2da` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`);

CREATE INDEX `categories_supervisors_42dc49bc` ON `categories_supervisors` (`category_id`);
CREATE INDEX `categories_supervisors_fbfc09f1` ON `categories_supervisors` (`user_id`);
