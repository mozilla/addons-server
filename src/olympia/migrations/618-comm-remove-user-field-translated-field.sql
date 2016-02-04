ALTER TABLE `comm_thread_notes` DROP FOREIGN KEY `thread_notes_body_key`;
ALTER TABLE `comm_thread_notes` DROP COLUMN `body`;
ALTER TABLE `comm_thread_notes` ADD COLUMN `body` longtext NULL;
