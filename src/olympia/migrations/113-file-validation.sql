CREATE TABLE `file_validation` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `file_id` integer NOT NULL,
    `valid` bool NOT NULL,
    `errors` integer NOT NULL,
    `warnings` integer NOT NULL,
    `notices` integer NOT NULL,
    `validation` longtext NOT NULL
);
ALTER TABLE `file_validation` ADD CONSTRAINT FOREIGN KEY (`file_id`) REFERENCES `files` (`id`);
