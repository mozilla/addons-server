DROP TABLE IF EXISTS `addons_dependencies`;
CREATE TABLE `addons_dependencies` (
    `id` int(11) NOT NULL AUTO_INCREMENT,
    `addon_id` int(11) NOT NULL,
    `dependent_addon_id` int(11) NOT NULL,
    PRIMARY KEY (`id`)
) DEFAULT CHARSET=utf8;

ALTER TABLE `addons_dependencies`
    ADD CONSTRAINT `addons_dependencies_addon_id_key`
    FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);

ALTER TABLE `addons_dependencies`
    ADD CONSTRAINT `addons_dependencies_dependent_addon_id_key`
    FOREIGN KEY (`dependent_addon_id`) REFERENCES `addons` (`id`);
