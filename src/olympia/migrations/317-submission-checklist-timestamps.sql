ALTER TABLE `submission_checklist_apps` ADD COLUMN `created` datetime NOT NULL;
ALTER TABLE `submission_checklist_apps` ADD COLUMN `modified` datetime NOT NULL;

CREATE INDEX `created_idx` ON `submission_checklist_apps` (`created`);
CREATE INDEX `modified_idx` ON `submission_checklist_apps` (`modified`);
