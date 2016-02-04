CREATE TABLE `validation_annotations` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `file_hash` varchar(255) NOT NULL,
    `message_key` varchar(1024) NOT NULL,
    `ignore_duplicates` bool,
    KEY `file_hash` (`file_hash`)
);
