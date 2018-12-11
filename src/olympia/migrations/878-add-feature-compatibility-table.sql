CREATE TABLE `addons_addonfeaturecompatibility` (
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL,
    `addon_id` int(11) UNSIGNED NOT NULL PRIMARY KEY,
    `e10s` smallint UNSIGNED NOT NULL
)
;
ALTER TABLE `addons_addonfeaturecompatibility` ADD CONSTRAINT `addon_id_refs_id_7779cd14` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);

