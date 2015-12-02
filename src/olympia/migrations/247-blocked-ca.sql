CREATE TABLE `blca` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `data` longtext NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
