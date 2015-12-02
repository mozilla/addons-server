CREATE TABLE `discovery_modules` (
    `id` int(11) UNSIGNED AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `app_id` integer NOT NULL,
    `module` varchar(255) NOT NULL,
    `ordering` integer,
    `locales` varchar(255) NOT NULL
);
