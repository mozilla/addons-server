CREATE TABLE `hero_secondaryhero` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime(6) NOT NULL,
    `modified` datetime(6) NOT NULL,
    `headline` varchar(50) NOT NULL,
    `description` varchar(100) NOT NULL,
    `cta_url` varchar(255) NOT NULL,
    `cta_text` varchar(20) NOT NULL,
    `enabled` boolean NOT NULL
)
;
ALTER TABLE `hero_secondaryhero`
ADD KEY `hero_secondaryhero_enabled_12e9da72` (`enabled`);
