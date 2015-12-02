CREATE TABLE `monolith_record` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `key` varchar(255) NOT NULL,
    `recorded` datetime NOT NULL,
    `user` varchar(255) NOT NULL,
    `anonymous` bool NOT NULL,
    `value` longtext NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;
;

CREATE INDEX `monolith_record_key` ON `monolith_record` (`key`);
CREATE INDEX `monolith_record_date` ON `monolith_record` (`recorded`);
