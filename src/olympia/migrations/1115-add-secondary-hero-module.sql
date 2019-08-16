CREATE TABLE `hero_secondaryheromodule` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime(6) NOT NULL,
    `modified` datetime(6) NOT NULL,
    `icon` varchar(255) NOT NULL,
    `description` varchar(50) NOT NULL,
    `cta_url` varchar(255) NOT NULL,
    `cta_text` varchar(20) NOT NULL,
    `shelf_id` integer NOT NULL
);
ALTER TABLE `hero_secondaryheromodule`
ADD CONSTRAINT `hero_secondaryheromo_shelf_id_dabb040a_fk_hero_seco`
FOREIGN KEY (`shelf_id`) REFERENCES `hero_secondaryhero` (`id`);
