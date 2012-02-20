CREATE TABLE `submission_checklist_apps` (
    `id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY,
    `addon_id` integer NOT NULL UNIQUE,
    `terms` bool NOT NULL,
    `manifest` bool NOT NULL,
    `details` bool NOT NULL,
    `payments` bool NOT NULL
) ENGINE=InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci;
ALTER TABLE `submission_checklist_apps` ADD CONSTRAINT
    FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`);
