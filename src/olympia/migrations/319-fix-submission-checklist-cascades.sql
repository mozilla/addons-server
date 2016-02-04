# This isn't my fourth migration for the same table. What are you talking about?
ALTER TABLE `submission_checklist_apps` DROP FOREIGN KEY `addons_id_pk`;
ALTER TABLE `submission_checklist_apps` ADD CONSTRAINT `addons_id_pk`
    FOREIGN KEY (`addon_id`) REFERENCES `addons` (`id`) ON DELETE CASCADE;
