# First drop indices.
DROP INDEX `created_idx` ON `submission_checklist_apps`;
DROP INDEX `modified_idx` ON `submission_checklist_apps`;

# Recreate table.
DROP TABLE `submission_checklist_apps`;
CREATE TABLE `submission_checklist_apps` (
    `id` int(11) unsigned AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `addon_id` int(11) unsigned NOT NULL UNIQUE,
    `terms` bool NOT NULL,
    `manifest` bool NOT NULL,
    `details` bool NOT NULL,
    `payments` bool NOT NULL,
    `created` datetime NOT NULL,
    `modified` datetime NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;

# This time cascade on delete. And name our constraint!
ALTER TABLE `submission_checklist_apps` ADD CONSTRAINT `addons_id_pk`
    FOREIGN KEY `addons` (`id`) REFERENCES `addons` (`id`) ON DELETE CASCADE;

# Recreate indices.
CREATE INDEX `created_idx` ON `submission_checklist_apps` (`created`);
CREATE INDEX `modified_idx` ON `submission_checklist_apps` (`modified`);
