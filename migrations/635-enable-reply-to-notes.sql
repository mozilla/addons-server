ALTER TABLE `comm_thread_notes` ADD COLUMN `read_permission_public` bool NOT NULL;
ALTER TABLE `comm_thread_notes` ADD COLUMN `read_permission_developer` bool NOT NULL;
ALTER TABLE `comm_thread_notes` ADD COLUMN `read_permission_reviewer` bool NOT NULL;
ALTER TABLE `comm_thread_notes` ADD COLUMN `read_permission_senior_reviewer` bool NOT NULL;
ALTER TABLE `comm_thread_notes` ADD COLUMN `read_permission_staff` bool NOT NULL;
ALTER TABLE `comm_thread_notes` ADD COLUMN `read_permission_mozilla_contact` bool NOT NULL;
ALTER TABLE `comm_thread_notes` ADD COLUMN `reply_to_id` int(11) unsigned;
ALTER TABLE `comm_thread_notes` ADD CONSTRAINT `reply_to_id_refs_id_df5d5709` FOREIGN KEY (`reply_to_id`) REFERENCES `comm_thread_notes` (`id`);

CREATE INDEX `comm_thread_notes_dev_perm` ON `comm_thread_notes` (`read_permission_developer`);
CREATE INDEX `comm_threads_dev_perm` ON `comm_threads` (`read_permission_developer`);
