CREATE TABLE `hero_primaryhero` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime(6) NOT NULL,
    `modified` datetime(6) NOT NULL,
    `image` varchar(255) NOT NULL,
    `background_color` varchar(7) NOT NULL,
    `enabled` bool NOT NULL,
    `disco_addon_id` integer NOT NULL UNIQUE
)
;
ALTER TABLE `hero_primaryhero`
ADD KEY `hero_primaryhero_enabled_12e9da72` (`enabled`),
ADD CONSTRAINT `hero_primaryhero_disco_addon_id_cf651633_fk_discovery`
FOREIGN KEY (`disco_addon_id`) REFERENCES `discovery_discoveryitem` (`id`);
