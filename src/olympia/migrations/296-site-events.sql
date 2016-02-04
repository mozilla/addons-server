CREATE TABLE `zadmin_siteevent` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `start` date NOT NULL,
    `end` date,
    `event_type` integer UNSIGNED NOT NULL,
    `description` varchar(255),
    `more_info_url` varchar(255)
);
