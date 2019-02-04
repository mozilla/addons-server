-- Note: if the migration fails for you locally, remove the 'unsigned' next to addon_id below.
CREATE TABLE `discovery_discoveryitem` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `created` datetime(6) NOT NULL,
    `modified` datetime(6) NOT NULL,
    `addon_id` integer UNSIGNED NOT NULL UNIQUE,
    `custom_addon_name` varchar(255) NOT NULL,
    `custom_heading` varchar(255) NOT NULL,
    `custom_description` longtext NOT NULL
)
;
ALTER TABLE `discovery_discoveryitem` ADD CONSTRAINT `addon_id_refs_id_93b5ecf8` FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);

-- Create group allowing users to edit discovery items in the admin.
INSERT INTO `groups` (name, rules, notes, created, modified)
    VALUES ('Discovery Recommendations Editors', 'Admin:Tools,Discovery:Edit', '', NOW(), NOW());
