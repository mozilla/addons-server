CREATE TABLE `addons_reusedguid` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime(6) NOT NULL,
    `modified` datetime(6) NOT NULL,
    `guid` varchar(255) NOT NULL,
    `addon_id` integer UNSIGNED NOT NULL UNIQUE
)
;
ALTER TABLE `addons_reusedguid`
ADD CONSTRAINT `addons_reusedguid_addon_id_32976f56_fk_addons_id`
FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
